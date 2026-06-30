# Telegram API (Commands)

The current Telegram interface is command-driven. No inline keyboards, reply keyboards, or callback-query APIs are implemented in the current project state.

## User

- `/start`
- `/help`
- `/kyc`
- `/price`
- `/wallet`
- `/buy`
- `/sell`
- `/receipt <order_id>`
- `/orders`
- `/cancelorder <order_id>`
- `/confirmcancel <order_id>`
- `/ticket <subject>`
- `/deposit <amount_usd>` with attachment
- `/withdraw <amount_usd>` with attachment

## Support

- `/replyticket <ticket_id> <message>` with optional attachment
- `/closeticket <ticket_id>`
- `/reopenticket <ticket_id>`
- `/internalticketnote <ticket_id> <message>`
- `/tickets [open|closed] [query]`

## Accountant

- `/approveorder <order_id>`
- `/rejectorder <order_id>`
- `/approvepayment <payment_id> [note]`
- `/rejectpayment <payment_id> [note]`
- `/pendingpayments`
- `/trialbalance`
- `/exporttrialbalance [csv|xlsx|pdf]`
- `/pnl`
- `/exportpnl [csv|xlsx|pdf]`
- `/balancesheet`
- `/exportbalancesheet [csv|xlsx|pdf]`
- `/cashflow`
- `/exportcashflow [csv|xlsx|pdf]`
- `/financialdashboard`
- `/dailyreport`
- `/weeklyreport`
- `/monthlyreport`
- `/yearlyreport`
- `/manualjournal <debit_code> <credit_code> <amount_usd> <description>`
- `/addbankaccount <name>|<account_number>`
- `/listbankaccounts`
- `/addcard <bank_account_id> <label>|<card_number>`
- `/listcards [bank_account_id]`

## Admin

- `/setprice <buy_price> <sell_price>`
- `/grantrole <telegram_id> <role>`
- `/reviewkyc <telegram_id> <approved|rejected|suspended|blocked> [note]`
- `/setrisk <name> <max_user_exposure_kg> <max_order_kg> <enabled true|false>`
- `/pendingcancels`
- `/approvecancel <order_id>`
- `/rejectcancel <order_id>`
- `/backup`
- `/restore` with encrypted backup attachment
- `/maintenance` to inspect current runtime mode
- `/maintenanceon [message]` to enable maintenance mode and show a banner to non-admin users
- `/maintenanceoff` to reopen the bot for standard traffic
- `/broadcast <message>` for all users
- `/broadcastrole <role> <message>` for role-scoped delivery
- `/broadcastlang <language_code> <message>` for language-targeted delivery
- `/broadcastkyc <status> <message>` for verification-status delivery
- `/broadcastactive <true|false> <message>` for trading-activity delivery
- `/broadcastschedule <ISO-8601 datetime> <message>` for deferred delivery
- Reply to a text/photo/document/video message and use `/broadcastreply` to queue a forwarded broadcast
