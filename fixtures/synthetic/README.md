# fixtures/synthetic/

This corpus is **entirely fictional**. "Dana Reyes," "Northwind Labs," every
correspondent name, every company domain, and every message body in this
directory was invented for testing purposes. No real person's mail is
included in this repository, and no message here was copied or adapted from
an actual email.

## Persona

**Dana Reyes** `<dana@northwind-labs.com>` — a consultant at a small firm
called Northwind Labs. 40 `.eml` messages, all sent *from* Dana, spanning
five categories:

| Category        | Count | Recipient domain                 |
|------------------|------:|-----------------------------------|
| Client           |    14 | external `@*.com`/`.io`/`.net`/`.org` clients |
| Internal         |    12 | `@northwind-labs.com` colleagues |
| Cold outreach    |     6 | external prospects               |
| Personal         |     5 | `@gmail.com` friends/family       |
| Terse acks       |     3 | mixed, under 15 words             |

## Designed traits

These traits are deliberate and statistically real in the data — downstream
tests assert that a style-extraction pipeline can recover them. If you add
or edit fixtures, keep these intact:

- **Short.** Most emails run 40-80 words of body prose (excluding
  signature-block boilerplate). The 3 terse acks are intentionally under 15
  words each; auto-replies and one templated outreach pair also run short.
- **Greeting convention.** Client, cold-outreach, and personal emails open
  with `Hi <name>,` (or a casual `Hey <name>,` for personal mail). Internal
  emails skip the greeting entirely and open directly with content.
- **Sign-off convention.** Internal and personal mail closes `— Dana`.
  Client and cold-outreach mail closes `Best,\nDana Reyes`, and 8 of those
  messages carry a full signature block (`Dana Reyes | Northwind Labs ...`).
- **Em dash habit.** Dana uses em dashes (`—`) heavily throughout, across
  every category.
- **Zero exclamation marks to clients.** No client or cold-outreach email
  contains a `!`. Internal and personal mail does occasionally, so the
  client-channel restraint is a real, detectable contrast rather than a
  corpus-wide absence.
- **Leads with the ask.** The first sentence after the greeting (or the
  opening sentence for internal mail) states the actual request or point —
  no throat-clearing preamble.
- **Pet phrase.** "worth a look" appears in 8 messages, spread across client,
  internal, outreach, and personal mail, phrased differently each time.

## Structural coverage

- **Quoted reply blocks (6 messages):** two in Gmail style (`On <date>
  <name> <email> wrote:` followed by `>`-quoted lines), two in Outlook style
  (`-----Original Message-----` header block), and two as bare `>`-prefixed
  quotes with no header — so parsing logic has to handle all three common
  shapes.
- **Signatures (8 messages):** full `--` signature-block footers on client
  mail.
- **Auto-replies (2 messages):** out-of-office autoresponses, one to a
  client, one to an internal colleague — no personalized greeting, generic
  template body.
- **Near-duplicate templated outreach (2 messages):** `outreach_001.eml` and
  `outreach_002.eml` share the same cold-outreach template with only the
  recipient name/company swapped, so dedupe logic has a real near-duplicate
  pair to catch.

## Why this matters

If this corpus reads as 40 copies of one template, or if the designed
traits above aren't genuinely present in the text (not just asserted in
this README), every downstream metric that claims to "recover Dana's
style" is validating against a fixture that begs the question. Wording is
varied deliberately across messages; only the two near-duplicate outreach
emails are meant to look alike.
