-- Fallback for accounts Mail has no IMAP/SMTP server for (Exchange, Outlook):
-- mail_draft.reply cannot file or send there directly, so this opens Mail's
-- own "reply" to get correct threading (In-Reply-To, References, recipients,
-- subject) and saves it as a draft. It does NOT attempt to set the body.
--
-- Mail 16 on macOS 26/27 renders a reply's body as a WebKit view (AXWebArea),
-- not the classic text control. Setting `content` of the reply, patching the
-- saved .emlx directly, and GUI-scripting real keystrokes into a genuinely
-- focused view were all tried and all three lose the text by the time the
-- draft is saved -- confirmed with a real coordinate click (focus verified
-- true) and a human-style Cmd+S. That is a Mail bug, not a scripting mistake;
-- there is no known workaround. So the draft comes back empty on purpose,
-- and the caller is told to type the body in Mail.
--
-- argv: 1 = account name, 2 = mailbox path, 3 = message id, 4 = replyAll
--       ("0" or "1")
-- Returns one record: subject, recipient count, draft id, draft mailbox path,
-- draft account name.

on run argv
	set accountName to item 1 of argv
	set mailboxPathText to item 2 of argv
	set messageIdentifier to (item 3 of argv) as integer
	set replyAll to (item 4 of argv) is "1"

	set theMessage to my findMessage(accountName, mailboxPathText, messageIdentifier)

	tell application "Mail"
		set knownIds to {}
		repeat with anOutgoing in outgoing messages
			try
				set end of knownIds to (id of anOutgoing)
			end try
		end repeat
		if replyAll then
			reply theMessage opening window true with reply to all
		else
			reply theMessage opening window true without reply to all
		end if
	end tell

	-- The reply window is created asynchronously; wait for it to show up.
	set theReply to missing value
	repeat with attemptNumber from 1 to 40
		delay 0.25
		tell application "Mail"
			repeat with anOutgoing in outgoing messages
				set outgoingId to missing value
				try
					set outgoingId to id of anOutgoing
				end try
				if outgoingId is not missing value and outgoingId is not in knownIds then
					set theReply to anOutgoing
					exit repeat
				end if
			end repeat
		end tell
		if theReply is not missing value then exit repeat
	end repeat
	if theReply is missing value then
		error "MAILERR:reply_window_missing:Mail did not open the reply"
	end if

	set draftIdentifier to ""
	set draftPath to ""
	set draftAccount to ""

	tell application "Mail"
		set theSubject to subject of theReply
		set recipientCount to (count of to recipients of theReply) + (count of cc recipients of theReply)

		set knownDraftIds to {}
		set snapshotTaken to false
		try
			if (count of messages of drafts mailbox) ≤ 500 then
				set knownDraftIds to id of messages of drafts mailbox
				set snapshotTaken to true
			end if
		end try

		save theReply
		-- Mail needs a moment to flush the save; closing immediately after can
		-- discard it even though "saving yes" was asked for.
		delay 0.5
		try
			close theReply saving yes
		end try

		if snapshotTaken then
			repeat with attemptNumber from 1 to 40
				delay 0.25
				try
					repeat with aDraft in (messages of drafts mailbox)
						set candidateId to id of aDraft
						if candidateId is not in knownDraftIds then
							set draftIdentifier to candidateId as text
							set draftPath to my fullMailboxPath(mailbox of aDraft)
							try
								set draftAccount to name of (account of (mailbox of aDraft))
							end try
							exit repeat
						end if
					end repeat
				end try
				if draftIdentifier is not "" then exit repeat
			end repeat
		end if
	end tell

	return my joinText({my cleanField(theSubject), recipientCount as text, draftIdentifier, my cleanField(draftPath), my cleanField(draftAccount)}, my fieldSep())
end run
