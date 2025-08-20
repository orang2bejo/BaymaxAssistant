# 📋 To-Do List: Deploy Baymax Assistant Online

## 🔥 Prioritas Tinggi (Critical)

### 1. Persiapan Kode untuk Production
- [ ] **Hapus debug mode dan optimasi konfigurasi**
  - Ubah `debug=True` menjadi `debug=False` di semua file
  - Set `reload=False` untuk uvicorn di production
  - Optimasi timeout dan connection settings

- [ ] **Buat environment variables untuk production**
  ```bash
  # Buat file .env.production
  GROQ_API_KEY=your_production_groq_key
  GROQ_MODEL=llama-3.3-70b-versatile
  GROQ_BASE_URL=https://api.groq.com/openai/v1
  
  OLLAMA_BASE_URL=http://localhost:11434
  OLLAMA_EMBED_MODEL=nomic-embed-text
  
  TTS_BASE_URL=http://localhost:5050
  TTS_MODEL=tts-1
  
  RAG_PERSIST_DIR=/app/rag_store
  ```

- [ ] **Optimasi requirements.txt**
  - Tambahkan versi spesifik untuk semua dependencies
  - Hapus development dependencies yang tidak perlu

### 2. Setup Hosting Server (VPS/Cloud)
- [ ] **Pilih provider hosting**
  - DigitalOcean ($5-10/bulan)
  - AWS EC2 (t2.micro free tier)
  - Google Cloud Compute Engine
  - Vultr ($2.50-5/bulan)

- [ ] **Spesifikasi server minimum**
  - RAM: 2GB minimum (4GB recommended)
  - Storage: 20GB SSD
  - CPU: 1-2 cores
  - OS: Ubuntu 22.04 LTS

- [ ] **Setup server dasar**
  ```bash
  # Update system
  sudo apt update && sudo apt upgrade -y
  
  # Install essential packages
  sudo apt install -y python3 python3-pip python3-venv nginx git curl
  
  # Install Docker
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  sudo usermod -aG docker $USER
  
  # Install Docker Compose
  sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
  ```

### 3. Setup Reverse Proxy dengan Nginx
- [ ] **Install dan konfigurasi Nginx**
  ```bash
  sudo apt install nginx -y
  sudo systemctl enable nginx
  sudo systemctl start nginx
  ```

- [ ] **Buat konfigurasi Nginx**
  ```nginx
  # /etc/nginx/sites-available/baymax
  server {
      listen 80;
      server_name your-domain.com www.your-domain.com;
      
      location / {
          proxy_pass http://localhost:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
      
      location /api/ {
          proxy_pass http://localhost:8000/api/;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
      }
  }
  ```

- [ ] **Aktifkan site**
  ```bash
  sudo ln -s /etc/nginx/sites-available/baymax /etc/nginx/sites-enabled/
  sudo nginx -t
  sudo systemctl reload nginx
  ```

### 4. Implementasi SSL/HTTPS
- [ ] **Install Certbot**
  ```bash
  sudo apt install certbot python3-certbot-nginx -y
  ```

- [ ] **Generate SSL certificate**
  ```bash
  sudo certbot --nginx -d your-domain.com -d www.your-domain.com
  ```

- [ ] **Setup auto-renewal**
  ```bash
  sudo crontab -e
  # Tambahkan line:
  0 12 * * * /usr/bin/certbot renew --quiet
  ```

### 5. Konfigurasi Security
- [ ] **Setup UFW Firewall**
  ```bash
  sudo ufw enable
  sudo ufw allow ssh
  sudo ufw allow 'Nginx Full'
  sudo ufw status
  ```

- [ ] **Install dan konfigurasi Fail2Ban**
  ```bash
  sudo apt install fail2ban -y
  sudo systemctl enable fail2ban
  sudo systemctl start fail2ban
  ```

- [ ] **Security hardening**
  ```bash
  # Disable root login
  sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
  
  # Change SSH port (optional)
  sudo sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config
  
  sudo systemctl restart ssh
  ```

## ⚡ Prioritas Menengah

### 6. Konfigurasi Domain & DNS
- [ ] **Beli domain**
  - Namecheap, GoDaddy, atau Cloudflare
  - Pilih domain yang mudah diingat

- [ ] **Setup DNS records**
  ```
  A Record: @ -> IP_SERVER
  A Record: www -> IP_SERVER
  CNAME Record: api -> your-domain.com
  ```

### 7. Containerization dengan Docker
- [ ] **Buat Dockerfile**
  ```dockerfile
  FROM python:3.10-slim
  
  WORKDIR /app
  
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  
  COPY . .
  
  EXPOSE 8000 5050
  
  CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
  ```

- [ ] **Buat docker-compose.yml**
  ```yaml
  version: '3.8'
  services:
    baymax-app:
      build: .
      ports:
        - "8000:8000"
      environment:
        - GROQ_API_KEY=${GROQ_API_KEY}
      volumes:
        - ./rag_store:/app/rag_store
      restart: unless-stopped
    
    ollama:
      image: ollama/ollama
      ports:
        - "11434:11434"
      volumes:
        - ollama_data:/root/.ollama
      restart: unless-stopped
  
  volumes:
    ollama_data:
  ```

### 8. Setup Process Manager
- [ ] **Install PM2**
  ```bash
  npm install -g pm2
  ```

- [ ] **Buat ecosystem.config.js**
  ```javascript
  module.exports = {
    apps: [{
      name: 'baymax-assistant',
      script: 'uvicorn',
      args: 'app:app --host 0.0.0.0 --port 8000',
      cwd: '/path/to/baymax_assistant/server',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production'
      }
    }]
  }
  ```

### 9. Testing & Deployment Final
- [ ] **Upload kode ke server**
  ```bash
  # Via Git
  git clone https://github.com/your-repo/baymax-assistant.git
  cd baymax-assistant/server
  
  # Setup virtual environment
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

- [ ] **Test semua functionality**
  - Test API endpoints
  - Test TTS functionality
  - Test RAG system
  - Test SSL certificate

- [ ] **Deploy dengan PM2 atau Docker**
  ```bash
  # PM2
  pm2 start ecosystem.config.js
  pm2 save
  pm2 startup
  
  # Docker
  docker-compose up -d
  ```

## 📊 Prioritas Rendah

### 10. Setup Monitoring & Logging
- [ ] **Install monitoring tools**
  ```bash
  # Install htop, netstat
  sudo apt install htop net-tools -y
  ```

- [ ] **Setup log rotation**
  ```bash
  sudo nano /etc/logrotate.d/baymax
  # Tambahkan konfigurasi log rotation
  ```

- [ ] **Optional: Setup Grafana + Prometheus**
  - Monitor server resources
  - Track API response times
  - Monitor error rates

## 🎯 Checklist Final

- [ ] Domain dapat diakses via HTTPS
- [ ] API endpoints berfungsi normal
- [ ] TTS service berjalan
- [ ] RAG system dapat query knowledge base
- [ ] SSL certificate valid
- [ ] Firewall dikonfigurasi dengan benar
- [ ] Auto-restart services berfungsi
- [ ] Backup strategy sudah disiapkan

## 💰 Estimasi Biaya Bulanan

- **Domain**: $10-15/tahun
- **VPS Hosting**: $5-20/bulan
- **SSL Certificate**: Gratis (Let's Encrypt)
- **Groq API**: Gratis (dengan limit)
- **Total**: ~$5-25/bulan

## ⏱️ Estimasi Waktu

- **Developer berpengalaman**: 1-2 hari
- **Developer pemula**: 3-5 hari
- **Maintenance**: 1-2 jam/bulan

---

**📝 Catatan**: Simpan semua credentials dan konfigurasi dengan aman. Buat backup regular dari database dan konfigurasi.