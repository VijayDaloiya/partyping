# PartyBing - Pune's Party & Balloon Decoration Service

## Live URL
https://partybing.in

## Admin Panel
- URL: https://partybing.in/admin
- Password: `partybing@2026`

## Tech Stack
- **Backend:** Python FastAPI + SQLite
- **Frontend:** HTML/CSS/JS (Jinja2 templates, no framework)
- **Server:** EC2 (Amazon Linux, Mumbai region) + Nginx + SSL (Let's Encrypt)
- **Port:** 8002 (behind Nginx reverse proxy)
- **Repo:** https://github.com/Shubh6378/partybing (private)

## Server Commands
```bash
# SSH into server
ssh ec2-user@13.200.119.43

# Deploy latest code
cd ~/apps/partybing && git pull && kill $(pgrep -f 'uvicorn.*8002') && nohup venv/bin/uvicorn main:app --host 127.0.0.1 --port 8002 > uvicorn.log 2>&1 &

# Check if running
ss -tlnp | grep 8002

# View logs
tail -f ~/apps/partybing/uvicorn.log
```

## Pages (33 indexable)

| Page | URL |
|------|-----|
| Home | https://partybing.in/ |
| Gallery | https://partybing.in/gallery |
| Contact | https://partybing.in/contact |
| Service Pages (x10) | https://partybing.in/services/{slug} |
| Locality Pages (x20) | https://partybing.in/area/{slug} |
| Admin | https://partybing.in/admin |
| Sitemap | https://partybing.in/sitemap.xml |
| Robots.txt | https://partybing.in/robots.txt |

### Services
birthday-decoration, balloon-decoration, anniversary-decoration, baby-shower-decoration, wedding-decoration, haldi-decoration, naming-ceremony, corporate-events, ring-ceremony, kids-party

### Localities
wakad, baner, hinjewadi, kothrud, hadapsar, viman-nagar, kharadi, magarpatta, pimpri-chinchwad, aundh, shivaji-nagar, koregaon-park, kalyani-nagar, bavdhan, ravet, nigdi, pimple-saudagar, katraj, undri, warje

## Performance Optimizations
- GZip compression (app-level middleware + Nginx)
- Static file caching (30 days)
- Upload caching (7 days)
- In-memory response cache (5 min TTL)
- Image auto-compression & WebP conversion on upload
- Non-render-blocking font loading
- Minimal JS (~2KB, no frameworks)
- Deferred script loading

## SEO Features
- LocalBusiness schema on every page
- Service schema on service pages
- FAQPage schema (homepage + service pages)
- Meta titles & descriptions (keyword-optimized for Pune)
- Canonical URLs
- Open Graph meta tags
- XML sitemap (33 URLs)
- robots.txt
- Locality pages targeting "decoration in {area}" searches
- Mobile-responsive design

## Admin Panel Features
- Dashboard with inquiry stats
- Manage services (name, price, description, SEO fields, FAQ)
- Gallery upload with auto image optimization
- Testimonials management
- Site settings (phone, address, social links)
- Inquiry status tracking (new → contacted → converted)

## DNS Setup
- **A Record:** `@` → `13.200.119.43`
- **SSL:** Let's Encrypt (auto-renews, expires 2026-08-08)
- **Note:** `www` subdomain needs A record pointed to `13.200.119.43` (currently on Vercel)

## Other Apps on Same Server
| App | Port | Domain |
|-----|------|--------|
| lead_generator | 8000 | leads.tkhata.in |
| partybing | 8002 | partybing.in |
| shopneeti | 3000 | shopneeti.tkhata.in |
| scanme | 8001 | tryscanme.com |

## Business Details
- **Name:** PartyBing
- **Phone/WhatsApp:** +91 9503146681
- **Email:** partybing0008@gmail.com
- **Address:** Shop No. 4, Pristic Arcade, Wakad, Pimpri-Chinchwad, Pune 411057
- **Default Price:** ₹2499
