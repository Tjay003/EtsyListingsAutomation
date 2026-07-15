# Friend Setup Guide

This folder is the simple install path for friends using the app locally on Windows.

The real scripts stay in the project root because they need to run beside `src`, `requirements.txt`, `.env`, and the `extension` folder. The numbered `.bat` files here are wrappers that call the root scripts.

## First Install

1. Install Python 3.11 or newer from `https://www.python.org/downloads/`.
   - During install, check `Add python.exe to PATH`.
2. Install Git from `https://git-scm.com/download/win`.
3. Clone the project from GitHub, or download the ZIP and extract the full ZIP first.
   - Do not run the `.bat` files from inside the ZIP preview.
   - Do not copy only the `friend-setup` folder; it needs the full project beside it.
4. Double-click `friend-setup/1-first-time-setup.bat`.
5. Open the generated `.env` file in the project root.
6. Add the private API keys Tyrone shares with you.
7. Double-click `friend-setup/2-start-app.bat`.
8. Open Chrome to `http://localhost:8000`.

## Chrome Extension

1. Open Chrome and go to `chrome://extensions/`.
2. Turn on `Developer mode`.
3. Click `Load unpacked`.
4. Select the project `extension` folder.
5. Open the extension popup settings.
6. Set Server URL to `http://localhost:8000`.
7. Set User Token to a personal workspace name, for example `friend-name`.
8. Use the same token in the dashboard when it asks for a Workspace Token.

## Daily Use

1. Double-click `friend-setup/2-start-app.bat`.
2. Keep the terminal window open while using the dashboard and extension.
3. If the app is already running, the script will open the existing dashboard instead of starting a second server.
4. Press `Ctrl+C` in the terminal to stop the app.

## Updating

1. Close the app terminal if it is running.
2. Double-click `friend-setup/3-update-app.bat`.
3. Start again with `friend-setup/2-start-app.bat`.

## Important Notes

- The real `.env` file is private and should never be uploaded to GitHub.
- Product data and generated images are stored on that friend's own computer under `OUTPUT_DIR`.
- The Workspace Token is just a local workspace divider. It is not a password.
- If AI features fail, first check that `.env` has `GEMINI_API_KEY` and `FAL_KEY`.
