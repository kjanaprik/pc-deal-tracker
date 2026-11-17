# RTX 50-Series Gaming PC Deal Tracker (Iceland & Global)

A GitHub-hosted scraper & deal-tracking dashboard for **Gaming Desktop PCs** equipped with:
- **RTX 5060 Ti 16GB**
- **RTX 5070 Ti 16GB**
- **RTX 5080 16GB**

## Tracked Stores

### Iceland (Local)
- **Tölvutækni** (`tolvutaekni.is`)
- **Computer.is** (`computer.is`)
- **Kísildalur** (`kd.is`)
- **Tölvulistinn** (`tl.is`)
- **Tölvutek** (`tolvutek.is`)
- **Elko** (`elko.is`)

### Europe (Ships Direct to Iceland)
- **Memory PC** (`memorypc.de`) — German builder; 19% DE VAT deducted on export
- **Computeruniverse** (`computeruniverse.net`) — 19% DE VAT deducted on export
- **Caseking** (`caseking.de`) — 19% DE VAT deducted on export
- **Overclockers UK** (`overclockers.co.uk`) — Ships via DHL Worldwide Express; 20% UK VAT removed
- **PCSpecialist** (`pcspecialist.co.uk`) — Ships to 30+ European countries including Iceland
- **CSL Computer** (`csl-computer.com`) — German custom PC builder
- **Amazon.de** & **Amazon.co.uk** — Amazon Global calculates Icelandic import VAT at checkout

### USA / Canada
- **B&H Photo** (`bhphotovideo.com`) — Ships directly to Iceland via DHL Express
- **Amazon.com** — Amazon Global shipping to Iceland on eligible systems
- **ORIGIN PC** (`originpc.com`) — Ships internationally to Iceland via custom freight quote
- **Best Buy** (`bestbuy.com`), **Newegg** (`newegg.com`), **Costco** (`costco.com`) — US/CA domestic (requires a freight forwarder such as MyUS or ShopUSA)

> **Landed Cost Formula (Iceland):** Foreign prices are automatically converted to ISK using live FX rates and adjusted for local VAT deduction (where applicable), estimated heavy-PC freight, **24% Icelandic VAT**, and **2.500 ISK** customs clearance.

---

## Setup on Your GitHub

1. **Create a new repository on GitHub** (e.g., `pc-deal-tracker`), then push this folder:
   ```bash
   git add .
   git commit -m "feat: initial RTX 50-series gaming PC deal tracker"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/pc-deal-tracker.git
   git push -u origin main
   ```

2. **Enable GitHub Pages**:
   - Go to **Settings → Pages**
   - Source: **Deploy from a branch** → `main` / `/ (root)` → **Save**
   - Your dashboard will be live at `https://<YOUR_USERNAME>.github.io/pc-deal-tracker/`

3. **Configure Email Notifications** (GitHub Secrets):
   Go to **Settings → Secrets and variables → Actions → New repository secret**:
   - **Option A — Resend (Recommended, free tier)**:
     - `NOTIFY_EMAIL`: your email address
     - `RESEND_API_KEY`: your API key from [resend.com](https://resend.com)
   - **Option B — Gmail / SMTP**:
     - `NOTIFY_EMAIL`: your email address
     - `SMTP_HOST`: `smtp.gmail.com`
     - `SMTP_PORT`: `587`
     - `SMTP_USER`: your Gmail address
     - `SMTP_PASS`: your Gmail App Password

4. **Optional API Keys for Bot-Protected US/EU/Amazon Sites**:
   Major US/EU sites (Amazon, Best Buy, Newegg, Caseking, Computeruniverse) block GitHub Actions datacenter IPs. You can unlock them by adding any of these optional secrets:
   - `BESTBUY_API_KEY`: Free official API key from [developer.bestbuy.com](https://developer.bestbuy.com)
   - `RAINFOREST_API_KEY`: Enables Amazon.com / Amazon.de / Amazon.co.uk
   - `SCRAPERAPI_KEY`: Enables Cloudflare-protected sites (Caseking, Computeruniverse, B&H, Newegg)
   - *Alternative*: Run the workflow on a [self-hosted GitHub Actions runner](https://docs.github.com/en/actions/hosting-your-own-runners) on your Mac.

5. **Watchlist & Black Friday Schedule**:
   - Click **☆ Watch** on any PC in the web dashboard, then click **Watchlist → Edit on GitHub** to save `watchlist.json` to your repo.
   - You can also add spec/price rules directly in `watchlist.json` (e.g. alert on any RTX 5070 Ti 16GB under 420.000 ISK).
   - GitHub Actions runs **every 2 hours** normally and automatically switches to **every 30 minutes** during Black Friday / Cyber Monday weekend (Nov 26–30).
