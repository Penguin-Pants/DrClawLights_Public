# Overview
- DrClawLights emails you a daily digest of randomly selected Kindle highlights
- It is used in combination with "HighlightsGrabber" https://github.com/Penguin-Pants/HighlightsGrabber, which exports your highlights as a JSON file
- It runs on www.railway.com and sends email through www.resend.com. The free tier is sufficient for sending 1 daily email
- A password-protected web dashboard manages the settings, the highlights file and test sends

## Setup
- Create a resend.com account and verify the domain of your sender address
- Deploy this project on www.railway.com
- Add a volume to the DrClawLights service and mount it at `/data`
- Set these variables on the service in Railway:
  - `ADMIN_PASSWORD`: the dashboard password (required). The dashboard is on the public internet, so use a long random value. Without it, nobody can log in
  - `RESEND_API_KEY`: your Resend API key (required)
  - `ANTHROPIC_API_KEY`: optional. Enables the "Echo" section (an AI-found connection between highlights from two books)
<BR>
<img width="1122" height="458" alt="image" src="https://github.com/user-attachments/assets/24b62574-7c7c-4747-900f-04c0ef1ed20c" />
<BR>

- Generate a public domain for the service in Railway and open it
- Keep Railway "Serverless" (app sleeping) OFF for this service. The daily send runs inside the web app, and a sleeping service sends nothing
- Keep one instance with one worker (the default start command). More would send duplicate emails

## Daily use (dashboard)
- Sign in with `ADMIN_PASSWORD`
- **Settings**: sender and recipient address, books per email, highlights per book, send time and timezone. Changes take effect immediately
- **Schedule**: the next digest time and the result of the last scheduled run
- **Highlights file**: upload the JSON file exported by HighlightsGrabber (any file name). It replaces the current file
- **Send now**: sends one digest immediately. Handy after an upload
- **Email Format**: design file, section toggles (Echo, Revisit, book covers), subject line and a live preview
<BR>
<img width="1920" height="1754" alt="DrClawLights_Settings" src="https://github.com/user-attachments/assets/e6656f44-78ae-499a-a55a-43e2e627c0d5" />
<BR>
<img width="1920" height="1232" alt="DrClawLights_Email" src="https://github.com/user-attachments/assets/51f01130-fbdd-4ece-be3c-a97e1805a56b" />
<BR>
## Other ways to test
- Copy the SSH command from Railway and connect
<BR>
<img width="330" height="220" alt="image" src="https://github.com/user-attachments/assets/89575dd7-095d-41ff-ad1f-c2c0a3d177e8" />
<BR>

- Once connected type: `python main.py --send-now`
- You should immediately get an email from DrClawLights

## Development
- `pip install -r requirements.txt pytest`
- `pytest -q` runs the test suite. GitHub Actions runs it on every push and pull request
- `uvicorn app:app --reload` runs the dashboard locally. Point the `*_FILE` variables from `.env.example` at local paths first

## Misc
- You need a Resend.com account
- You need a Github account
- You need a railway.com account linked to your forked version of this github project
- An Anthropic API key is optional. Only the Echo section uses it
