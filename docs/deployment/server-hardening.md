# Server Hardening Guide

How to deploy Dead-Man-Newsletter on an EC2 instance (or any Ubuntu VPS) securely.
This guide uses Docker to run the app behind nginx with Let's Encrypt SSL.

## Security Model

- **No SSH port open.** Use AWS SSM Session Manager for shell access instead.
- **Only ports 80 and 443** are open to the internet.
- **nginx** handles SSL termination and proxies to the app on localhost:5000.
- **fail2ban** is configured for SSH protection as a safety net (dormant while port 22 is closed).

---

## 1. EC2 Security Group

In the AWS console, set your instance's security group inbound rules to:

| Type  | Protocol | Port | Source    |
|-------|----------|------|-----------|
| HTTP  | TCP      | 80   | 0.0.0.0/0 |
| HTTPS | TCP      | 443  | 0.0.0.0/0 |

**Do not add an SSH rule (port 22).** You will use SSM Session Manager instead.

---

## 2. AWS SSM Session Manager (Shell Access Without SSH)

SSM Session Manager gives you a terminal session to your EC2 instance with no open ports.

**One-time setup:**

1. Attach the `AmazonSSMManagedInstanceCore` IAM policy to your EC2 instance role.
2. Ensure the SSM Agent is running (it's pre-installed on Amazon Linux 2 and Ubuntu 20.04+):
   ```bash
   sudo systemctl status amazon-ssm-agent
   ```

**Starting a session:**
```bash
# From your local machine (requires AWS CLI + session-manager-plugin)
aws ssm start-session --target i-0123456789abcdef0
```

Or use the AWS Console: **EC2 → Instances → [your instance] → Connect → Session Manager**.

---

## 3. System Updates and Non-Root User

```bash
sudo apt update && sudo apt upgrade -y

# Create a deploy user
sudo useradd -m -s /bin/bash deploy
sudo usermod -aG docker deploy

# Switch to deploy user for all app operations
sudo su - deploy
```

---

## 4. UFW Firewall (Second Layer)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# Do NOT open port 22 — using SSM
sudo ufw enable
sudo ufw status
```

Expected output:
```
Status: active
To                         Action      From
--                         ------      ----
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
```

---

## 5. Install Docker

```bash
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 6. Deploy the App

```bash
# As the deploy user
cd /home/deploy
git clone https://github.com/youruser/Dead-Man-Newsletter.git app
cd app

# Create .env from example and fill in your SMTP credentials
cp .env.example .env
nano .env

# Set newsletter.db permissions
touch newsletter.db
chmod 600 newsletter.db

# Start the app
docker compose up -d
```

Verify it's running:
```bash
curl http://localhost:5000/
# Should return a redirect (HTTP 302)
```

---

## 7. nginx Reverse Proxy

```bash
sudo apt install -y nginx
```

Create `/etc/nginx/sites-available/newsletter`:

```nginx
server {
    listen 80;
    server_name newsletter.yourdomain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/newsletter /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 8. Let's Encrypt SSL (Certbot)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d newsletter.yourdomain.com
```

Follow the prompts. Certbot will:
1. Obtain a certificate from Let's Encrypt
2. Automatically update your nginx config to serve HTTPS
3. Set up an HTTP → HTTPS redirect

**Test auto-renewal:**
```bash
sudo certbot renew --dry-run
```

**Auto-renewal cron** (runs twice daily — standard Certbot recommendation):
```bash
sudo crontab -e
```
Add:
```
0 3,15 * * * certbot renew --quiet
```

---

## 9. fail2ban (SSH Protection)

fail2ban monitors log files and bans IPs that show brute-force behaviour.
Port 22 is currently closed, so this is dormant — but it activates automatically if SSH is ever opened.

```bash
sudo apt install -y fail2ban
```

Create `/etc/fail2ban/jail.local`:
```ini
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
backend = %(syslog_backend)s
```

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
sudo fail2ban-client status sshd
```

---

## 10. Keep the App Running with systemd

Create `/etc/systemd/system/newsletter.service`:

```ini
[Unit]
Description=Dead-Man-Newsletter Docker App
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/deploy/app
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=deploy

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable newsletter
sudo systemctl start newsletter
```

---

## 11. Final Checklist

- [ ] EC2 security group: only ports 80 and 443 open
- [ ] SSM Session Manager working (tested a session)
- [ ] UFW enabled with only ports 80 and 443
- [ ] App running: `docker compose ps` shows `Up`
- [ ] nginx serving HTTP: `curl http://newsletter.yourdomain.com` → redirect
- [ ] SSL working: `curl https://newsletter.yourdomain.com` → app
- [ ] Certbot renewal tested: `sudo certbot renew --dry-run`
- [ ] fail2ban running: `sudo fail2ban-client status`
- [ ] systemd service enabled: `sudo systemctl is-enabled newsletter`
- [ ] `newsletter.db` permissions: `ls -la newsletter.db` shows `-rw-------`
- [ ] Base URL set in app Settings to `https://newsletter.yourdomain.com`
