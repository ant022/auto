# auto24 price tracker

Checks the price of the listings in `cars.json` once a day (GitHub Actions) and shows the history on a simple page (`index.html`, GitHub Pages).

## Setup
1. Create a new GitHub repo and upload all these files (keep the `.github/workflows` folder structure).
2. Repo **Settings > Actions > General > Workflow permissions**: choose "Read and write permissions".
3. Repo **Settings > Pages**: Source = "Deploy from a branch", Branch = `main`, folder `/ (root)`.
4. **Actions** tab > "Daily car price check" > **Run workflow** (first test run).
5. Your site: `https://<your-username>.github.io/<repo-name>/`

## Add a car
Add another entry to `cars.json`:
```json
{ "url": "https://www.auto24.ee/soidukid/1234567", "note": "optional label" }
```

## If a run shows ERROR
auto24 may be blocking GitHub's servers. The run saves a screenshot and HTML under the run's "debug" artifact. See the chat for fallbacks (run it from your own computer instead).

## Run locally
```
pip install -r requirements.txt
playwright install chromium
python scrape_cars.py
python -m http.server   # then open http://localhost:8000
```
