# Trading Bot Starter with Android App

This is a beginner-safe Python trading bot starter with a mobile dashboard.

Right now it does four things:

1. Logs in to IG demo.
2. Reads prices for symbols in `earnings_watchlist.csv`.
3. Follows simple earnings timing windows.
4. Prints and logs paper-trading signals.

It does not place real trades.

## Android App (PWA)

The dashboard is now a Progressive Web App (PWA) that can be installed on Android devices:

1. Open the dashboard in Chrome on your Android device: `http://your-server-ip:5000`
2. Tap the menu (three dots) > "Add to Home screen"
3. The app will appear on your home screen like a native app.

Features:
- View open/closed positions
- P/L summary and analytics
- Trade logs
- Auto-refresh every 10 seconds
- Offline caching

## Step 1: Install Python

Install Python from:

https://www.python.org/downloads/

During install, tick:

```text
Add Python to PATH
```

After install, close VS Code and open it again.

## Step 2: Install Libraries

Open Terminal in VS Code and run:

```powershell
python -m pip install -r requirements.txt
```

## Step 3: Create `.env`

Create a file named:

```text
.env
```

Copy the contents of `.env.example` into `.env`, then replace the values with your real new keys.

Important: do not share `.env`.

## Step 4: Run

```powershell
python main.py
```

Stop the bot with:

```text
Ctrl + C
```

## Step 5: Edit Earnings Watchlist

Open:

```text
earnings_watchlist.csv
```

Use this format:

```text
symbol,earnings_datetime,active,notes
TSLA,2026-05-10 21:30,yes,Tesla earnings
```

The time format must be:

```text
YYYY-MM-DD HH:MM
```

For now, use your local computer time.

To pause a symbol, set active to `no`:

```text
TSLA,2026-05-10 21:30,no,Tesla paused
```

## Step 6: Read The Log

The bot creates:

```text
trades_log.csv
```

This file stores every base price and signal check.

The bot also creates:

```text
paper_trades.csv
```

This file stores only useful paper trade ideas and avoids duplicate repeated signals.

The bot also creates:

```text
demo_orders.csv
```

This file stores IG demo order attempts.

## Step 7: Optional IG Demo Auto Trade

This is disabled by default.

Open `.env` and keep this off until you are ready:

```text
AUTO_DEMO_TRADING=false
MAX_DEMO_TRADES_PER_RUN=1
AUTO_CLOSE_DEMO_POSITIONS=true
DEMO_TAKE_PROFIT_AMOUNT=2500
DEMO_STOP_LOSS_AMOUNT=700
AUTO_SIGNAL_DEMO_TRADING=true
SIGNAL_DEMO_NOTIONAL_USD=500
MAX_SIGNAL_DEMO_TRADES_PER_ROUND=3
SIGNAL_CANDIDATE_POOL_SIZE=10
MIN_SIGNAL_QUALITY=0.6
CALL_SIGNAL_THRESHOLD_PERCENT=1.0
PUT_SIGNAL_THRESHOLD_PERCENT=-1.0
FADE_SIGNAL_THRESHOLD_PERCENT=0.25
```

Open:

```text
demo_trade_plan.csv
```

Set only one row to `active=yes`.

Example:

```text
BTC,Bitcoin,BUY,0.01,yes,Small demo test
```

Then enable demo trading:

```text
AUTO_DEMO_TRADING=true
```

Run:

```powershell
python main.py
```

After the test, turn it off again:

```text
AUTO_DEMO_TRADING=false
```

Open demo positions are checked every bot cycle. If `AUTO_CLOSE_DEMO_POSITIONS=true`, the bot tries to close a demo position when:

```text
Profit >= 2500
Loss <= -700
```

## Step 8: Local Dashboard

Install requirements:

```powershell
python -m pip install -r requirements.txt
```

Start the dashboard:

```powershell
python dashboard.py
```

Open:

```text
http://127.0.0.1:5000
```

## Cloud Deployment

### Railway Deployment (Recommended)

1. **Create Railway Account**: Go to [railway.app](https://railway.app) and sign up.

2. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

3. **Deploy to Railway**:
   ```bash
   cd /path/to/your/project
   railway init
   railway up
   ```

4. **Set Environment Variables** in Railway dashboard:
   - `IG_API_KEY`
   - `IG_USERNAME`
   - `IG_PASSWORD`
   - `FINNHUB_API_KEY`
   - `PAPER_TRADING=true`
   - `AUTO_DEMO_TRADING=true` (set to false for initial testing)
   - Other variables from `.env.example`

5. **Access Your App**: Railway will provide a URL like `https://your-app.railway.app`

### Heroku Deployment (Alternative)

1. **Create Heroku Account**: Go to [heroku.com](https://heroku.com) and sign up.

2. **Install Heroku CLI**:
   ```bash
   # Download from https://devcenter.heroku.com/articles/heroku-cli
   heroku login
   ```

3. **Deploy to Heroku**:
   ```bash
   cd /path/to/your/project
   heroku create your-app-name
   heroku config:set IG_API_KEY=your_key
   heroku config:set IG_USERNAME=your_username
   # Set all other environment variables...
   git init
   git add .
   git commit -m "Initial commit"
   git push heroku main
   ```

4. **Access Your App**: `https://your-app-name.herokuapp.com`

### Post-Deployment Setup

1. **Test the Dashboard**: Visit your cloud URL and ensure the dashboard loads.

2. **Enable Trading**: Once tested, set `AUTO_DEMO_TRADING=true` in your cloud environment variables.

3. **Monitor Logs**: Use Railway/Heroku dashboards to monitor application logs.

4. **Data Persistence**: CSV files are stored in the app directory and persist between deployments.

### Important Notes

- The bot runs trading cycles every 5 minutes when `AUTO_DEMO_TRADING=true`
- All CSV files (positions, trades, logs) are stored in the cloud and persist
- Environment variables must be set in your cloud platform's dashboard
- The dashboard is publicly accessible - consider adding authentication for production use

Or double-click:

```text
run_dashboard.bat
```

The dashboard reads:

```text
open_positions.csv
closed_positions.csv
positions_log.csv
paper_trades.csv
demo_orders.csv
trades_log.csv
```
