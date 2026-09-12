#!/usr/bin/env bash
# Only stdout is the sudo askpass protocol. Never enable tracing here.
set +x
set -Eeuo pipefail

VLDB_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PASSWORD_FILE=${VLDB_ROOT}/password.conf

die()
{
    printf 'sudo_askpass: %s\n' "$*" >&2
    exit 1
}

if (($# == 1)) && [[ "$1" == -h || "$1" == --help ]]; then
    printf '%s\n' 'Internal sudo askpass helper. Use ./sudo_exec.sh; do not invoke this helper directly.'
    exit 0
fi

[[ "${VLDB_SUDO_ASKPASS_ACTIVE:-0}" == 1 ]] || die 'use ./sudo_exec.sh'
[[ "${VLDB_SUDO_CALLER_UID:-}" =~ ^[0-9]+$ ]] || die 'missing caller identity'
[[ "${VLDB_SUDO_CALLER_UID}" == "$(id -u)" ]] || die 'caller identity mismatch'
[[ -f "${PASSWORD_FILE}" && ! -L "${PASSWORD_FILE}" && -r "${PASSWORD_FILE}" ]] ||
    die 'password.conf must be a readable regular file, not a symlink'
[[ "$(realpath -e -- "${PASSWORD_FILE}")" == "${PASSWORD_FILE}" ]] || die 'unexpected password.conf path'
[[ "$(stat -c %u -- "${PASSWORD_FILE}")" == "${VLDB_SUDO_CALLER_UID}" ]] ||
    die 'password.conf must be owned by the invoking user'
[[ "$(stat -c %a -- "${PASSWORD_FILE}")" == 600 ]] || die 'run chmod 600 password.conf'

# Parse data literally; password.conf is never sourced or evaluated as shell code.
password=
while IFS= read -r line || [[ -n "${line}" ]]; do
    line=${line%$'\r'}
    line=${line#"${line%%[![:space:]]*}"}
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    if [[ "${line}" =~ ^[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][[:space:]]*[:=][[:space:]]*(.*)$ ]]; then
        line=${BASH_REMATCH[1]}
    fi
    password=${line}
    break
done <"${PASSWORD_FILE}"

[[ -n "${password}" ]] || die 'password.conf has no password entry; edit it on the execution host'
printf '%s\n' "${password}"
