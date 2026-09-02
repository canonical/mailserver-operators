#!/usr/bin/env bash

set -euo pipefail

: "${CONTROLLER_NAME:?Set CONTROLLER_NAME}"
: "${MODEL_UUID:?Set MODEL_UUID}"
: "${MAIL_DOMAIN:?Set MAIL_DOMAIN}"
EXPECT_DKIM="${EXPECT_DKIM:-false}"

MODEL="${CONTROLLER_NAME}:${MODEL_UUID}"
STATUS_JSON="$(juju status -m "${MODEL}" --format json)"
DOVECOT_UNIT="$(
    jq -er '.applications.dovecot.units | keys | first' <<<"${STATUS_JSON}"
)"
POSTFIX_UNIT="$(
    jq -er '.applications["postfix-relay"].units | keys | first' <<<"${STATUS_JSON}"
)"
POSTFIX_IP="$(
    jq -er \
        '.applications["postfix-relay"].units | to_entries | first | .value["public-address"]' \
        <<<"${STATUS_JSON}"
)"

printf 'Disposable mailbox password: ' >&2
stty -echo
trap 'stty echo' EXIT INT TERM
IFS= read -r MAIL_PASSWORD
stty echo
trap - EXIT INT TERM
printf '\n' >&2
test -n "${MAIL_PASSWORD}" || {
    echo "Mailbox password must not be empty" >&2
    exit 1
}

juju run -m "${MODEL}" "${DOVECOT_UNIT}" create-mail-user \
    username=alice mailbox-user="alice@${MAIL_DOMAIN}" \
    password="${MAIL_PASSWORD}" --wait=5m
juju run -m "${MODEL}" "${DOVECOT_UNIT}" create-mail-user \
    username=bob mailbox-user="bob@${MAIL_DOMAIN}" \
    password="${MAIL_PASSWORD}" --wait=5m

SUBJECT="staging mail acceptance test $(date +%s)"

juju exec -m "${MODEL}" --unit "${POSTFIX_UNIT}" -- \
    bash -c \
    'printf "From: alice@%s\nTo: bob@%s\nSubject: %s\n\nPS7 staging mail test.\n" "$1" "$1" "$2" |
      sudo /usr/sbin/sendmail -v -f "alice@$1" "bob@$1"' \
    _ "${MAIL_DOMAIN}" "${SUBJECT}"

for _ in $(seq 1 20); do
    MESSAGE_HEADERS="$(
        juju exec -m "${MODEL}" --unit "${DOVECOT_UNIT}" -- \
            bash -c \
            'sudo doveadm fetch -u bob \
              "hdr.subject hdr.from hdr.to hdr.dkim-signature" \
              mailbox INBOX header Subject "$1"' \
            _ "${SUBJECT}"
    )"
    if grep -F "hdr.subject: ${SUBJECT}" <<<"${MESSAGE_HEADERS}" >/dev/null; then
        break
    fi
    sleep 3
done

printf '%s\n' "${MESSAGE_HEADERS}"
grep -F "hdr.subject: ${SUBJECT}" <<<"${MESSAGE_HEADERS}" >/dev/null
if [[ "${EXPECT_DKIM}" == "true" ]]; then
    grep -F "hdr.dkim-signature: v=1;" <<<"${MESSAGE_HEADERS}" >/dev/null
elif grep -F "hdr.dkim-signature: v=1;" <<<"${MESSAGE_HEADERS}" >/dev/null; then
    echo "Unexpected DKIM signature while OpenDKIM is disabled" >&2
    exit 1
fi

juju exec -m "${MODEL}" --unit "${DOVECOT_UNIT}" -- \
    bash -c 'sudo cryptsetup status mail-data && findmnt /srv/mail'

juju exec -m "${MODEL}" --unit "${DOVECOT_UNIT}" -- \
    python3 -c '
import smtplib
import sys

with smtplib.SMTP(sys.argv[1], 25, timeout=30) as smtp:
    smtp.ehlo()
    code, response = smtp.mail(f"alice@{sys.argv[2]}")
    assert code < 400, (code, response)
    code, response = smtp.rcpt("outsider@example.net")
    assert code >= 400, f"open relay detected: {code} {response!r}"
    print(f"PASS: external relay rejected with SMTP {code}")
' "${POSTFIX_IP}" "${MAIL_DOMAIN}"

printf '\nPASS: sendmail delivery, Dovecot retrieval, LUKS storage, and relay rejection verified.\n'
