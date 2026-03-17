# DNS Setup Guide

How to point a domain name at your Dead-Man-Newsletter server so that tracking pixels
and unsubscribe links work from inside email clients.

## Prerequisites

- A running server with a **static public IP address** (e.g. an EC2 Elastic IP)
- A domain name you control (e.g. `newsletter.yourdomain.com`)

## What You're Doing

You're creating an **A record** — a DNS entry that maps a hostname to an IP address.
Once propagated, `https://newsletter.yourdomain.com` will resolve to your server.

Then you set that URL as the **Base URL** in Dead-Man-Newsletter's Settings page.

---

## AWS Route 53

1. Go to **Route 53 → Hosted Zones** and click your domain.
2. Click **Create record**.
3. Fill in:
   - **Record name:** `newsletter` (creates `newsletter.yourdomain.com`)
   - **Record type:** `A`
   - **Value:** Your server's public IP address
   - **TTL:** `300` (5 minutes — change to `3600` once stable)
4. Click **Create records**.

---

## GoDaddy

1. Go to **My Products → DNS** for your domain.
2. Click **Add New Record**.
3. Fill in:
   - **Type:** `A`
   - **Host:** `newsletter`
   - **Points to:** Your server's public IP address
   - **TTL:** `600 seconds`
4. Click **Save**.

---

## Squarespace

1. Go to **Domains → [your domain] → DNS Settings**.
2. Under **Custom Records**, click **Add Record**.
3. Fill in:
   - **Type:** `A`
   - **Host:** `newsletter`
   - **Data:** Your server's public IP address
   - **TTL:** `3600`
4. Click **Save**.

---

## Namecheap

1. Go to **Domain List → [your domain] → Advanced DNS**.
2. Under **Host Records**, click **Add New Record**.
3. Fill in:
   - **Type:** `A Record`
   - **Host:** `newsletter`
   - **Value:** Your server's public IP address
   - **TTL:** `Automatic`
4. Click the green checkmark to save.

---

## Cloudflare

1. Go to **[your domain] → DNS → Records**.
2. Click **Add record**.
3. Fill in:
   - **Type:** `A`
   - **Name:** `newsletter`
   - **IPv4 address:** Your server's public IP address
   - **Proxy status:** **DNS only** (grey cloud) — do NOT proxy through Cloudflare unless you've configured SSL termination on your server
   - **TTL:** `Auto`
4. Click **Save**.

---

## Verify Propagation

DNS changes can take a few minutes to a few hours to propagate. Check with:

```bash
# From any machine
dig newsletter.yourdomain.com
nslookup newsletter.yourdomain.com 8.8.8.8
```

Both should return your server's IP address.

You can also use https://dnschecker.org to see propagation status worldwide.

---

## Set Base URL in the App

Once DNS resolves correctly and SSL is configured (see `server-hardening.md`):

1. Open Dead-Man-Newsletter → **Settings**
2. Set **Base URL** to `https://newsletter.yourdomain.com`
3. Click **Save Settings**

Tracking pixels and unsubscribe links in all future emails will now use this URL.
