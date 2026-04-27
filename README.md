# Playto Payout System

A concurrency-safe payout engine with:
- Row-level locking (PostgreSQL)
- Idempotency guarantees
- Ledger-based accounting
- Async processing

## 📘 Deep Dive (Explainer.md)
👉 [Full Explanation](./EXPLAINER.md)

## 🌐 Live Demo

### Frontend (Vercel)
👉 https://playto-payout-kappa.vercel.app/

### View Merchant Information
👉 https://playto-payout-4yks.onrender.com/api/v1/merchants/

> ⚠️ Note: The backend is hosted on Render's free tier.  
> If the API has been idle, the first request may take **30–60 seconds (or more)** as the server spins back up.  
> Initial loading of resources may take some time.
