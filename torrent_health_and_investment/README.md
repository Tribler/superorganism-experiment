# SwarmHealth - Creative Commons Torrent Health Checker

SwarmHealth is a health monitoring tool for Creative Commons licensed torrents. It tracks seeding levels, peer counts, and calculates growth metrics to monitor the health of torrent swarms.

**Clone the repo using the --recursive flag for the ipv8 submodule:**

```
git clone --recursive https://github.com/hmcostaa/SwarmHealth-Checker.git
```

## Features

- **Health Monitoring**: Tracks seeders, leechers, and total peer counts for torrents
- **Metrics Calculation**:
  - **Growth**: Percentage change in peer count over time
  - **Shrink**: Measures how much a swarm is shrinking
  - **Exploding Estimator**: Score (0-100) indicating rapid swarm growth
- **Creative Commons Filtering**: Only monitors torrents with Creative Commons licenses
- **Retry Logic**: Automatically retries health checks if DHT returns empty results
- **GUI Dashboard**: Beautiful graphical interface showing real-time metrics
- **CSV Integration**: Loads torrent data from CSV files with magnet links

## Requirements

- Python 3.12
- libtorrent (python-libtorrent)
- tkinter (usually included with Python, required for GUI)

**If tkinter not installed:**

```
sudo apt install python3-tk
```

## Virtual Environment

1. **Create Environment:**

```
python -m venv /path/to/new/virtual/environment
```

2. **Activate Environment:**

_Windows:_

```
/path/to/new/virtual/environment\Scripts\activate
```

_macOS/Linux:_

```
source /path/to/new/virtual/environment/bin/activate
```

## Installation

1. **Install Python dependencies:**

   ```bash
   python -m pip install --upgrade -r requirements.txt
   ```

2. **Verify installation:**

   ```bash
   python -c "import libtorrent; print('libtorrent version:', libtorrent.version)"
   ```

3. **Install the py-ipv8 submodule in development mode:**

   ```bash
   cd py-ipv8 && pip install -e .
   ```

## CSV File Format

Create a CSV file with the following columns:

| Column        | Description                                                  | Required                  |
| ------------- | ------------------------------------------------------------ | ------------------------- |
| `url`         | URL for the content                           	       | Yes                       |
| `license`     | License type (must contain "Creative Commons" for filtering) | Yes                       |
| `magnet_link` | BitTorrent magnet link                                       | Yes (for health checking) |

### Example CSV (`torrents.csv`):

```csv
url,license,magnet_link
https://example.com/content1,Creative Commons CC-BY,magnet:?xt=urn:btih:IDFDBHSSHMWIG5PFDAVSRCHZKVAHT66U
https://example.com/content2,Creative Commons CC0,magnet:?xt=urn:btih:JKME5Y27D4E6SXSQYISKW4FXOWSD5DQG
```

**Note**: The application only processes entries with Creative Commons licenses. Entries without magnet links will be skipped.

## Usage

### GUI Mode (Recommended)

Launch the graphical interface:

```bash
python -m healthchecker --gui torrents_template.csv
```

Or with a custom CSV file path:

```bash
python -m healthchecker --gui /path/to/your/torrents.csv
```

**GUI Features:**

- Real-time metrics display
- Statistics dashboard (Total, Healthy, No Peers, Exploding)
- Sortable table with all metrics
- Auto-refresh every 30 seconds
- Start/Stop health checker controls
- Log window for operations

### Command-Line Mode

Run without GUI:

```bash
python -m healthchecker torrents_template.csv
```

### IPV8 Mode

Receive torrents from peers via IPV8 network instead of CSV:

```bash
python -m healthchecker --mode ipv8
```

With GUI:

```bash
python -m healthchecker --mode ipv8 --gui
```

### Possible Issues

If any case like me you find yourself running this program on Windows (worst OS ever), you may encounter the following error:

```
ImportError: DLL load failed while importing libtorrent: The specified module could not be found.
```

Following some discussions on libtorrent issues, I managed to track it to necessary dependencies that for some reason are missing, in particular _libcrypto-1_1-x64.dll_ and _libssl-1_1-x64.dll_, and basically it is necessary to install them manually.

The health checker will:

- Load Creative Commons entries from CSV
- Randomly select torrents for health checks
- Query DHT and connect to torrents for detailed stats
- Calculate growth, shrink, and exploding metrics
- Store results in SQLite database (`dht_health.db`)
- Run continuously with 5-minute intervals

**Press Ctrl+C to stop**

## Metrics Explained

### Seeders

Number of peers that have the complete file and are uploading.

### Leechers

Number of peers that are downloading and don't have the complete file yet.

### Total Peers

Sum of seeders and leechers.

### Growth (%)

Percentage change in peer count compared to the previous check.

- Positive: Swarm is growing
- Negative: Swarm is shrinking
- Example: `+15.5%` means 15.5% more peers than last check

### Shrink (%)

Measures how much a swarm is shrinking (inverse of negative growth).

- Only shows positive values when shrinking
- Example: `10.2%` means the swarm shrunk by 10.2%

### Exploding Estimator (0-100)

A composite score indicating rapid swarm growth:

- **0-30**: Normal growth
- **30-50**: Moderate growth
- **50-70**: High growth
- **70-100**: Explosive growth

The score considers:

- Recent growth rate
- Acceleration (rate of change)
- Number of samples
- Current peer count

## Database

Health check results are stored in `dht_health.db` (SQLite database). The database includes:

- Historical peer counts
- Seeder/leecher counts
- Calculated metrics (growth, shrink, exploding)
- Timestamps for each check
- Source URLs and license information

## Retry Logic

If a DHT query returns no peers:

1. The system waits 60 seconds
2. Retries the health check (up to 3 attempts)
3. If still no peers after retries, records as "no_peers"

## Troubleshooting

### "CSV file not found"

- Ensure the CSV file path is correct
- Check that the file exists and is readable

### "No Creative Commons entries available"

- Verify your CSV has entries with "Creative Commons" in the license column
- Check for typos in license names

### "No peers found"

- This is normal for new or inactive torrents
- The system will retry automatically
- Check that magnet links are valid

### GUI doesn't start

- Ensure tkinter is installed: `python -m tkinter` (should open a window)
- On Linux, you may need: `sudo apt-get install python3-tk`

### libtorrent errors

- Ensure python-libtorrent is properly installed
- Try: `pip install --upgrade python-libtorrent`
- Check that you have the correct version for your Python version

## File Structure

```
SwarmHealth/
├── healthchecker/
│   ├── __init__.py
│   ├── __main__.py          # Main entry point
│   ├── client.py            # DHT client and torrent connection
│   ├── csv_loader.py        # CSV file loading and filtering
│   ├── db.py                # Database operations
│   ├── gui.py               # Graphical user interface
│   ├── metrics.py           # Metrics calculations
│   └── sampler.py           # Health checker main logic
├── requirements.txt
├── README.md
└── torrents_template.csv    # Example CSV format
```

---

**⚠️ Important**: This tool is for monitoring Creative Commons licensed torrents only. Do not use for copyrighted content.
