# Waste Form Manager

A lightweight, dependency-free (except for Flask) web application built with Python and SQLite for tracking and managing stock waste. This application allows users to maintain a database of stock items, create waste forms by logging quantities of wasted items, and export those records to CSV and PDF formats.

It is also fully **Docker ready**, making deployment and scaling incredibly easy.

## Features

- **Stock Management**: Add, update, and bulk-delete stock items (Stock Code & Product Description).
- **Waste Tracking**: Create "Waste Forms" by assigning quantities to existing stock items.
- **Form Management**: View a history of all waste forms, edit existing forms, and delete mistakes.
- **Exporting**: Export any waste form directly to `.csv` or `.pdf`.
  - *Note: PDF generation is built entirely from scratch using Python's standard library, requiring no heavy external PDF dependencies!*
- **Auto-Seeding**: Automatically seeds the database on startup if a `Stock Items.csv` file is present in the root directory.
- **Docker Ready**: Easily spin up the app in an isolated container environment.

## Prerequisites

- **Python 3.7+** (If running locally)
- **Docker** & **Docker Compose** (If running via container)

---

## 🐳 Running with Docker (Recommended)

Running the app via Docker is the easiest way to get started without worrying about local Python environments.

### 1. Build and Run using Docker CLI
To build the image and run it on port 5000:

```bash
# Build the Docker image
docker build -t waste-form-manager .

# Run the container (with a volume to persist the database)
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e DB_PATH=/app/data/waste_forms.db \
  --name waste_manager \
  waste-form-manager
```
*Note: We mount a local `./data` folder to `/app/data` inside the container and point the `DB_PATH` to it. This ensures your database isn't deleted if the container stops.*

### 2. Using Docker Compose
If you have a `docker-compose.yml` file set up, you can simply run:

```bash
docker-compose up -d --build
```
The application will be accessible at `http://localhost:5000`.

---

## 💻 Local Installation & Setup (Without Docker)

1. **Clone or Download the Repository**
   Ensure all files are placed in your project folder.

2. **Create a Virtual Environment (Recommended)**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install Dependencies**
   The only external dependency required is Flask.
   ```bash
   pip install flask
   ```

4. **Directory Structure Requirements**
   Ensure you have a `templates` folder in the same directory as `app.py` containing your HTML files:
   ```text
   .
   ├── app.py
   ├── Stock Items.csv        # (Optional) For auto-seeding data
   └── templates/
       ├── index.html
       ├── forms.html
       └── form_detail.html
   ```

5. **Run the Application**
   ```bash
   python app.py
   ```
   The app will automatically initialize the SQLite database (`waste_forms.db`) and start a local development server at `http://127.0.0.1:5000`.

---

## Configuration (Environment Variables)

You can customize the application's behavior using the following environment variables (works both locally and in Docker):

| Variable | Description | Default Value |
| :--- | :--- | :--- |
| `SECRET_KEY` | Flask secret key used for securely signing session cookies and flash messages. | `dev-secret-key` |
| `DB_PATH` | The absolute or relative path where the SQLite database will be stored. | `waste_forms.db` (in the app directory) |

*Local Example (Linux/macOS):*
```bash
export SECRET_KEY="my-super-secure-key"
export DB_PATH="/path/to/my/custom_database.db"
python app.py
```

---

## Auto-Seeding Stock Data

If you want to pre-populate the application with stock items, place a file named `Stock Items.csv` in the root directory before starting the app (or building the Docker image). 

The application will look for columns named exactly:
- `Stock Code`
- `Pack Description`

It will read these columns and safely inject them into the database upon initial startup.

---

## Usage Guide

1. **Home Page (`/`)**: 
   - View your current stock items.
   - Add new items manually via the "Add Stock Item" form.
   - Fill out quantities next to items and click "Save", "Export CSV", or "Export PDF" to generate a Waste Form.
   - Select multiple items to delete them in bulk.
2. **Forms List (`/forms`)**:
   - View a historical list of all saved waste forms, including when they were created and how many items were recorded.
3. **Form Details (`/forms/<id>`)**:
   - View the exact contents of a specific past waste form.
   - Edit the form to correct mistakes.
   - Re-export the form to CSV or PDF at any time.