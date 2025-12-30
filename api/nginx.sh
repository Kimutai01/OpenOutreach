sudo nano /etc/nginx/sites-available/chrome.nexuscale.ai 

```
server {
    listen 80;
    listen [::]:80;

    server_name  chrome.nexuscale.ai www.chrome.nexuscale.ai;

    root /var/www/html;  # Update the path to your website's root directory
    index index.html index.htm;

    location / {
        proxy_pass http://localhost:8000/;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }


    # Additional configurations can be added here, such as SSL/TLS settings or PHP handling
}

```

sudo rm /etc/nginx/sites-enabled/chrome.nexuscale.ai 

sudo ln -s /etc/nginx/sites-available/chrome.nexuscale.ai  /etc/nginx/sites-enabled/

sudo certbot --nginx -d chrome.nexuscale.ai -d www.chrome.nexuscale.ai

sudo nginx -t

sudo systemctl reload nginx
