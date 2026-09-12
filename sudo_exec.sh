#!/usr/bin/env bash
# The password travels only from the helper's stdout to sudo, never as an argument.
set +x
set -Eeuo pipefail

VLDB_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ASKPASS=${VLDB_ROOT}/sudo_askpass.sh
PASSWORD_FILE=${VLDB_ROOT}/password.conf
SUDO=/usr/bin/sudo

usage()
{
    cat <<'EOF'
Usage: ./sudo_exec.sh experiments/run_fig5.py [OPTIONS...]
       ./sudo_exec.sh experiments/plot_fig5.py RESULT_DIRECTORY [OPTIONS...]
       ./sudo_exec.sh --check

Use this host's repository-root password.conf (owned by you, mode 600).
Run commands receive a 2 GiB memlock limit. --check tests sudo access only.
Only the Figure 5 runners and plotters in this checkout may be launched.
EOF
}

die()
{
    printf 'sudo_exec: %s\n' "$*" >&2
    exit 1
}

if (($# == 1)) && [[ "$1" == -h || "$1" == --help ]]; then
    usage
    exit 0
fi
(($# >= 1)) || { usage >&2; exit 2; }

if (($# == 1)) && [[ "$1" == --check ]]; then
    command=(/usr/bin/true)
    shift
else
    [[ -f "$1" && ! -L "$1" && -r "$1" ]] || die 'target must be a readable regular script'
    target=$(realpath -e -- "$1") || die 'cannot resolve target'
    shift
    case "${target}" in
        "${VLDB_ROOT}/experiments/run_fig5.py" | \
        "${VLDB_ROOT}/experiments/run_fig5_local.py" | \
        "${VLDB_ROOT}/experiments/run_fig5_fio.py")
            command=(/usr/bin/prlimit --memlock=2147483648:2147483648 /usr/bin/python3 "${target}") ;;
        "${VLDB_ROOT}/experiments/plot_fig5.py" | \
        "${VLDB_ROOT}/experiments/plot_fig5_local.py" | \
        "${VLDB_ROOT}/experiments/plot_fig5_fio.py")
            command=(/usr/bin/python3 "${target}") ;;
        *) die 'only Figure 5 runners and plotters in this checkout are allowed' ;;
    esac
fi

if (( EUID == 0 )); then
    exec "${command[@]}" "$@"
fi

[[ -x "${SUDO}" ]] || die 'sudo is not installed at /usr/bin/sudo'
[[ -f "${ASKPASS}" && ! -L "${ASKPASS}" && -x "${ASKPASS}" ]] || die 'missing executable sudo_askpass.sh'
[[ -f "${PASSWORD_FILE}" && ! -L "${PASSWORD_FILE}" && -r "${PASSWORD_FILE}" ]] ||
    die 'create password.conf in this checkout and run chmod 600 password.conf'
caller_uid=$(id -u)
[[ "$(stat -c %u -- "${PASSWORD_FILE}")" == "${caller_uid}" ]] ||
    die 'password.conf must be owned by the invoking user'
[[ "$(stat -c %a -- "${PASSWORD_FILE}")" == 600 ]] || die 'run chmod 600 password.conf'

export SUDO_ASKPASS=${ASKPASS}
export VLDB_SUDO_ASKPASS_ACTIVE=1
export VLDB_SUDO_CALLER_UID=${caller_uid}
exec "${SUDO}" -A -p '' -- "${command[@]}" "$@"
