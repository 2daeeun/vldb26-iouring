"""Read-only NVMe preflight and exclusive ownership for explicitly selected raw runs.

No formatting, unmounting, partition changes, or driver reconfiguration is done here.
Only a whole, unused PCIe NVMe namespace is accepted, never a partition or a file.
"""

import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

SYS = Path("/sys")
PROC = Path("/proc")
NVME_IOCTL_ID = 0x4E40  # _IO('N', 0x40), linux/nvme_ioctl.h


def read(path):
    return path.read_text().strip()


def optional_read(path):
    return read(path) if path.exists() else None


def device_identity(path, kind):
    path = path.resolve(strict=True)
    st = path.stat()
    if not (stat.S_ISBLK(st.st_mode) if kind == "block" else stat.S_ISCHR(st.st_mode)):
        raise ValueError(f"Expected {kind} device, got {path}")
    dev = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    return dict(path=str(path), dev=dev, sysfs=str((SYS / "dev" / kind / dev).resolve(strict=True)))


def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def mounted_on(device_numbers):
    mounts = []
    for line in read(PROC / "self/mountinfo").splitlines():
        fields = line.split()
        separator = fields.index("-")
        source = unescape_mount(fields[separator + 2])
        matches = fields[2] in device_numbers
        try:
            st = Path(source.split("[")[0]).stat()
            matches |= stat.S_ISBLK(st.st_mode) and f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}" in device_numbers
        except OSError:
            pass
        if matches:
            mounts.append(dict(target=unescape_mount(fields[4]), source=source))
    return mounts


def swaps_on(device_numbers):
    swaps = []
    for line in read(PROC / "swaps").splitlines()[1:]:
        path = Path(unescape_mount(line.split()[0]))
        st = path.stat()
        dev = st.st_rdev if stat.S_ISBLK(st.st_mode) else st.st_dev
        if f"{os.major(dev)}:{os.minor(dev)}" in device_numbers:
            swaps.append(str(path))
    return swaps


def inspect_pcie(controller, min_width=None):
    """Record the endpoint and upstream links, starting nearest the namespace.

    Follow sysfs ancestry instead of assuming a PCI address or slot. A smaller
    endpoint than an upstream port is normal; compare capabilities per link.
    """
    links, warnings, errors = [], [], []
    fields = ("current_link_width", "max_link_width", "current_link_speed",
              "max_link_speed", "numa_node")
    for path in controller.resolve().parents:
        if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", path.name):
            continue
        link = dict(address=path.name, sysfs=str(path))
        for field in fields:
            try:
                value = optional_read(path / field)
            except OSError:
                value = None
            if field.endswith("width"):
                value = int(value) if value and value.isdigit() and int(value) > 0 else None
            link[field] = value
        links.append(link)
    endpoint = links[0] if links else None
    if not endpoint or endpoint["current_link_width"] is None:
        warnings.append("NVMe PCIe link width is unavailable; bandwidth readiness is unverified")
    elif endpoint["max_link_width"] and endpoint["current_link_width"] < endpoint["max_link_width"]:
        warnings.append(f"NVMe PCIe link is x{endpoint['current_link_width']} but the SSD supports "
                        f"x{endpoint['max_link_width']}; check the adapter and slot before comparing Figure 5 performance")
    if min_width is not None:
        if not links or any(link["current_link_width"] is None for link in links):
            errors.append(f"Cannot verify --min-pcie-width {min_width}: PCIe link width unavailable")
        for link in links:
            width = link["current_link_width"]
            if width is not None and width < min_width:
                errors.append(f"PCIe {link['address']} is x{width}; --min-pcie-width {min_width} requires "
                              f"at least x{min_width}. Check the adapter/slot; polling flags do not increase lane width")
    return dict(links=links, min_width=min_width, warnings=warnings, errors=errors)


def inspect_nvme(block, char, require_poll, required_bytes, min_pcie_width=None):
    block_id = device_identity(block, "block")
    char_id = device_identity(char, "char")
    block_name = Path(block_id["path"]).name
    char_name = Path(char_id["path"]).name
    ns_path, char_path = Path(block_id["sysfs"]), Path(char_id["sysfs"])
    if not re.fullmatch(r"nvme\d+n\d+", block_name) or (ns_path / "partition").exists():
        raise ValueError("--nvme-block must be a whole NVMe namespace, not a partition")
    if char_name != block_name.replace("nvme", "ng", 1) or char_path.parent != ns_path.parent:
        raise ValueError("Block and generic character device do not identify the same NVMe namespace")
    controller = ns_path.parent
    if read(controller / "transport") != "pcie":
        raise ValueError("Raw mode currently supports direct PCIe NVMe namespaces only")
    nodes = [ns_path] + sorted(p for p in ns_path.iterdir() if (p / "partition").is_file())
    numbers = {read(node / "dev") for node in nodes}
    info = dict(block=block_id, char=char_id, namespace_id=int(read(ns_path / "nsid")),
                size_bytes=int(read(ns_path / "size")) * 512,
                model=read(controller / "model"), serial=read(controller / "serial"),
                firmware=optional_read(controller / "firmware_rev"),
                wwid=optional_read(ns_path / "wwid"), diskseq=optional_read(ns_path / "diskseq"),
                numa_node=optional_read(controller / "numa_node"),
                partitions=[node.name for node in nodes[1:]],
                mounts=mounted_on(numbers), swaps=swaps_on(numbers),
                holders={node.name: [p.name for p in (node / "holders").iterdir()] for node in nodes},
                read_only=read(ns_path / "ro"),
                logical_block_size=int(read(ns_path / "queue/logical_block_size")),
                metadata_bytes=optional_read(ns_path / "metadata_bytes"),
                command_set=optional_read(ns_path / "csi"),
                poll_queues=optional_read(SYS / "module/nvme/parameters/poll_queues"),
                io_poll=optional_read(ns_path / "queue/io_poll"))
    info["pcie"] = inspect_pcie(controller, min_pcie_width)
    info["warnings"] = info["pcie"]["warnings"]
    errors = list(info["pcie"]["errors"])
    if info["mounts"]:
        errors.append("Raw namespace or its partitions are mounted: " + str(info["mounts"]))
    if info["swaps"]:
        errors.append("Raw namespace contains active swap: " + str(info["swaps"]))
    if any(info["holders"].values()):
        errors.append("Raw namespace is held by another block device: " + str(info["holders"]))
    if info["read_only"] != "0":
        errors.append("Raw namespace is read-only")
    if info["size_bytes"] < required_bytes:
        errors.append(f"Raw namespace needs at least {required_bytes} bytes")
    if info["logical_block_size"] not in (512, 1024, 2048, 4096):
        errors.append("Unsupported NVMe logical block size")
    if info["metadata_bytes"] not in (None, "0") or info["command_set"] not in (None, "0"):
        errors.append("Only metadata-free NVM namespaces are supported")
    if require_poll and (not info["poll_queues"] or int(info["poll_queues"]) < 1 or info["io_poll"] != "1"):
        errors.append("IOPoll/SQPoll require active polling queues: boot with nvme.poll_queues=1 "
                      "and verify poll_queues > 0 and queue/io_poll=1")
    info["errors"] = errors
    return info


def verify_namespace_ids(block, char, expected_nsid):
    # These ioctls only return namespace IDs; they submit no data write commands.
    for path in (block, char):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            if fcntl.ioctl(fd, NVME_IOCTL_ID, 0) != expected_nsid:
                raise ValueError(f"NVMe namespace ID mismatch: {path}")
        finally:
            os.close(fd)


def physical_core(cpu):
    root = SYS / f"devices/system/cpu/cpu{cpu}/topology"
    return read(root / "physical_package_id"), read(root / "core_id")


def choose_sqpoll_cpu(worker, node, allowed, requested=None):
    candidates = [requested] if requested is not None else sorted(allowed, key=lambda cpu: (cpu <= worker, cpu))
    for cpu in candidates:
        if (cpu in allowed and (SYS / f"devices/system/node/node{node}/cpu{cpu}").exists()
                and physical_core(cpu) != physical_core(worker)):
            return cpu
    raise ValueError("SQPoll needs a second allowed physical core on the selected NUMA node "
                     "(use --sqpoll-cpu; an SMT sibling of the worker is not sufficient)")


def same_device(first, second):
    keys = ("block", "char", "namespace_id", "size_bytes", "wwid", "diskseq", "serial")
    return all(first[key] == second[key] for key in keys)


@contextmanager
def claim_namespace(args, previous):
    """Hold an exclusive block-device claim until every benchmark child exits."""
    if args.confirm_device is None or args.confirm_device != args.nvme_block:
        raise ValueError("Raw writes destroy data and partition tables. Actual execution requires "
                         "--confirm-device with the same whole-namespace path as --nvme-block")
    current = inspect_nvme(args.nvme_block, args.nvme_char,
                           bool({"iopoll", "sqpoll"} & set(args.cases)), args.file_bytes,
                           args.min_pcie_width)
    if current["errors"] or not same_device(current, previous):
        raise ValueError("Raw device changed or is in use: " + str(current["errors"]))
    # Unlike an advisory flock, O_EXCL detects filesystem holders in other mount
    # namespaces too, and blocks new mounts of this disk while the claim is held.
    fd = os.open(args.nvme_block, os.O_RDWR | os.O_EXCL | os.O_CLOEXEC)
    try:
        verify_namespace_ids(args.nvme_block, args.nvme_char, current["namespace_id"])
        yield fd
    finally:
        os.close(fd)
