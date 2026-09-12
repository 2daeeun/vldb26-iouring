#pragma once

// NVMe uring_cmd returns a command status (zero on success), whereas a page
// read/write returns a byte count. Positive NVMe errors are not successful I/O.
inline bool page_io_succeeded(int result, bool nvme_cmds) {
    return result == (nvme_cmds ? 0 : 4096);
}
