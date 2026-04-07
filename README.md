# page-watcher
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
edit .env file according to .env.example, currently it uses TG bot to send notification

```bash
python3 monitor.py
```

to run the service as a linux demon:
sudo nano /etc/systemd/system/page-watcher.service
```ini
[Unit]
Description=Page Watcher Monitor Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/page-watcher
ExecStart=/home/ubuntu/page-watcher/venv/bin/python3 monitor.py
EnvironmentFile=/home/ubuntu/page-watcher/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

restart the demon:
```bash
sudo systemctl daemon-reload
sudo systemctl restart page-watcher
sudo systemctl status page-watcher
sudo journalctl -u page-watcher -f
```

you can delete the service by:
```bash
sudo systemctl stop page-watcher
sudo systemctl disable page-watcher
sudo rm /etc/systemd/system/page-watcher.service
sudo systemctl daemon-reload
```

update the code on server:
```bash
git pull origin main
sudo systemctl restart page-watcher
```

add the watchdog to crontab:
```bash
sudo crontab -e
```
add the following to run the watchdog every 30 minutes
```cron
*/30 * * * * /home/ubuntu/page-watcher/venv/bin/python /home/ubuntu/page-watcher/watchdog.py >> /home/ubuntu/page-watcher/cron.log 2>&1
```

## OCI ARM Instance Launcher

The OCI ARM launcher is integrated into the watchdog and automatically attempts to create Oracle Cloud ARM always-free instances every 30 minutes (when the watchdog runs) until successful.

The launcher will:
- Automatically install OCI CLI and dependencies if missing
- Attempt to create VM.Standard.A1.Flex instance (4 OCPUs, 24GB RAM)
- Retry every 30 minutes when capacity is unavailable
- Send notification via Telegram/Discord on success
- Stop running after successful instance creation
- Report status in weekly watchdog reports

No additional setup required - it runs automatically with the existing watchdog cron job.

Check logs:
```bash
tail -f oci_arm_launcher.log
tail -f watchdog.log
```