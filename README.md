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
