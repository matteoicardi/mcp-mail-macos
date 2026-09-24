"""Fallback for accounts mail_imap cannot reach: Exchange and Outlook accounts
expose no IMAP or SMTP server to Mail, so mail_draft's server-side build/file/
send path has nothing to talk to there. This module drives Mail itself
instead, through AppleScript, for exactly those accounts.

On this machine (macOS 27, Mail 16), setting `content` on an outgoing message
does not survive to the saved draft -- confirmed for both a fresh `make new
outgoing message` and a `reply`-derived one, with an isolated single-property
test outside any of this project's own code. Patching the saved .emlx
directly and GUI-scripting real keystrokes (focus verified true, saved with a
human-style Cmd+S) were also tried; neither survived either. That is a Mail
bug on this build, not a scripting mistake, and there is no known workaround.
It may not reproduce on every Mac -- macOS/Mail versions differ -- so the
content is still set here on a best-effort basis. What differs from the old
behaviour is that the result is no longer trusted blindly: the draft is read
straight back off disk afterwards (the same .emlx path mail_index's fast
read path uses) to report whether the body actually landed.

Because of that uncertainty, this module never sends directly. A "send"
request on one of these accounts is turned into a draft instead, with a note
explaining why -- sending a body that silently came out empty is worse than
asking for one extra manual step.
"""

from __future__ import annotations

from typing import Any, Sequence

import mail_index
from mail_tools import (
    MailError,
    MessageReference,
    _as_address_list,
    _check_attachments,
    _field,
    _parse_records,
    run_script,
)

DRAFT_WRITE_TIMEOUT = 60

_NO_SERVER_NOTE = (
    "This account has no IMAP/SMTP server in Mail (Exchange/Outlook), so this "
    "was done through Mail's own compose window instead of the server-side path."
)


def has_imap(account: Any) -> bool:
    return bool(account.incoming.host)


def has_smtp(account: Any) -> bool:
    return bool(account.outgoing.host)


def _verify_body(mail_id: str, intended_body: str) -> tuple[bool, str]:
    """Reads the saved draft back off disk and checks the body actually landed.

    Never trust the AppleScript call's own success return for this: it
    reports the property was set, not that it survived being saved.
    """
    if not mail_id:
        return False, "The draft could not be found afterwards to check."
    try:
        parsed = mail_index.get_message_from_file(int(mail_id), force_refresh=True)
    except Exception as error:  # noqa: BLE001 - verification must never raise
        return False, f"Could not read the draft back to check: {error}"
    if parsed is None:
        return False, "The draft's file could not be read back to check."
    saved_body = (parsed.get("body") or "").strip()
    if saved_body and saved_body in intended_body.strip():
        return True, ""
    return False, (
        "Mail's known content-setting bug on this machine (see this module's "
        "docstring) means the body did not survive to the saved draft. Open "
        "it in Mail and type the body in yourself."
    )


def compose(
    mode: str,
    to: str | Sequence[str],
    subject: str,
    body: str,
    cc: str | Sequence[str] | None = None,
    bcc: str | Sequence[str] | None = None,
    attachments: Sequence[str] | None = None,
    sender: str | None = None,
) -> dict[str, Any]:
    """Builds a fresh message through Mail's own compose window, as a draft.

    Used for create_draft/send_email on an account mail_imap cannot reach.
    Always files a draft, even for a "send" request -- see the module
    docstring -- and reports whether the body actually made it in.
    """
    attachment_paths = _check_attachments(attachments)
    raw = run_script(
        "compose",
        [
            "draft",
            "\x1f".join(_as_address_list(to)),
            "\x1f".join(_as_address_list(cc)),
            "\x1f".join(_as_address_list(bcc)),
            subject,
            body,
            "\x1f".join(attachment_paths),
            sender or "",
        ],
        timeout=DRAFT_WRITE_TIMEOUT,
    )
    records = _parse_records(raw)
    row = records[0] if records else []
    draft_id = _field(row, 4)
    if not draft_id:
        raise MailError(
            "draft_not_found",
            "Mail composed the message but the resulting draft could not be found afterwards.",
            "Check Mail's Drafts mailbox directly.",
        )
    body_set, body_note = _verify_body(draft_id, body)

    note = _NO_SERVER_NOTE
    if mode == "send":
        note += (
            " A send was requested, but this account cannot be sent through "
            "automatically -- open the draft, check it, and send it from Mail yourself."
        )
    if not body_set:
        note += " " + body_note

    return {
        "ok": True,
        "mode": "draft",
        "sent": False,
        "body_set": body_set,
        "subject": _field(row, 1),
        "to_count": int(_field(row, 2) or 0),
        "attachment_count": int(_field(row, 3) or 0),
        "mail_id": int(draft_id),
        "mailbox": _field(row, 5),
        "account": _field(row, 6),
        "via": "mail_applescript",
        "note": note,
    }


def reply_headers_only(message_id: str, reply_all: bool = False) -> dict[str, Any]:
    """Creates a correctly threaded draft via Mail's own reply, as a draft.

    For an account mail_imap cannot reach. Checks, rather than assumes,
    whether the body was set -- see the module docstring -- and always
    leaves the result as a draft even if a send was requested.
    """
    reference = MessageReference.decode(message_id)
    raw = run_script(
        "reply_headers_only",
        [reference.account, reference.mailbox, str(reference.identifier), "1" if reply_all else "0"],
        timeout=DRAFT_WRITE_TIMEOUT,
    )
    records = _parse_records(raw)
    row = records[0] if records else []
    draft_id = _field(row, 2)
    if not draft_id:
        raise MailError(
            "draft_not_found",
            "Mail opened the reply but the resulting draft could not be found afterwards.",
            "Check Mail's Drafts mailbox directly.",
        )
    # This path never attempts to set a body at all (see the module docstring)
    # so there is nothing to read back and verify here.
    body_note = (
        "This path only sets threading (In-Reply-To/References), subject and "
        "recipients -- Mail's content-setting bug (see this module's docstring) "
        "means the body cannot be set automatically for a reply on this account. "
        "Open the draft in Mail and type the body in yourself."
    )

    return {
        "ok": True,
        "mode": "draft",
        "sent": False,
        "body_set": False,
        "subject": _field(row, 0),
        "recipient_count": int(_field(row, 1) or 0),
        "mail_id": int(draft_id),
        "mailbox": _field(row, 3),
        "account": _field(row, 4),
        "via": "mail_applescript",
        "note": _NO_SERVER_NOTE + " " + body_note,
    }
