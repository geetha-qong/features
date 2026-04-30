# Qong — P&ID Valve List Extractor

AI-powered tool that extracts structured valve lists and instrumentation indexes from scanned P&ID drawings (PDFs). Upload a PDF, get a CSV.

**Live app:** https://dev.theqong.com

---

## System Requirements

| Requirement | Minimum |
|-------------|---------|
| OS | macOS 12+, Ubuntu 20.04+, or Windows 11 (WSL2) |
| RAM | 8 GB |
| Disk | 10 GB free |
| Docker Desktop | 4.x or later |
| Git | Any recent version |

> **Everything runs in Docker.** You do not need Python, nginx, or any other service installed on your machine.

---

## First-Time Setup

### 1. Install Docker Desktop

Download and install from https://www.docker.com/products/docker-desktop  
After install, open Docker Desktop and wait until the whale icon in the menu bar is steady (not animated).

### 2. Clone the repo

```bash
git clone git@github.com:Qong-Systems/qong_product.git
cd qong_product
```

### 3. Create the `.env` file

Copy the example and fill in the values:

```bash
cp .env.example .env
```

Open `.env` and set:

```env
OPENROUTER_API_KEY=sk-or-...        # Get from team lead — required for PDF extraction
SECRET_KEY=any-random-string-here   # Used to sign login cookies — make something up
LS_API_KEY=                         # Leave blank for now, set after Label Studio first run (Step 6)
```

> Ask your team lead for the `OPENROUTER_API_KEY`.

### 4. Build and start the app

```bash
docker compose up -d web nginx
```

This builds the Docker image (takes ~2 min on first run) and starts:
- **Webapp** at http://localhost:8000
- **nginx proxy** at http://localhost:9000

### 5. Open the webapp

Go to http://localhost:8000  
Login with: `admin` / `Qong@2024`

Upload any P&ID PDF and you should see a job queued on the dashboard.

### 6. (Optional) Start Label Studio for annotation

Label Studio is the tool used to annotate P&ID tiles for YOLO model training.

```bash
docker compose up -d label-studio
```

Open http://localhost:8080 and register with:
- Email: `tnb@qongsystems.com`
- Password: `Qong@2024`

Then get your API token:  
**Account & Settings → Access Token → Copy**

Paste it into `.env`:
```env
LS_API_KEY=your-token-here
```

Restart the web container to pick up the new key:
```bash
docker compose restart web
```

---

## Daily Usage

```bash
# Start everything
docker compose up -d web nginx

# Start with Label Studio too
docker compose up -d web label-studio nginx

# Stop everything
docker compose down

# View logs
docker compose logs -f web
```

---

## Annotation Labels (13 classes)

When annotating tiles in Label Studio, use **exactly** these label names:

### Valves
| Label | Symbol |
|-------|--------|
| `valve_bf` | Butterfly — bowtie / diamond shape |
| `valve_bv` | Ball — circle with line through it |
| `valve_ck` | Check — arrowhead or half-circle |
| `valve_gl` | Globe — circle with plug/bonnet on top |
| `valve_db` | Double Block & Bleed — cluster of 3 small symbols |
| `valve_cv` | Control valve — circle with dome actuator on top |
| `valve_gen` | Generic (gate, needle, safety, pressure, flow valves) |

### Actuators
| Label | Symbol |
|-------|--------|
| `actuator_motor` | Square box with letter **M** |
| `actuator_pneu` | Dome/diaphragm shape above valve |
| `actuator_sol` | Box labelled **SL** or coil symbol |

### Instruments
| Label | Symbol |
|-------|--------|
| `inst_bubble` | Circle with tag text (PT, TT, FT, LT, PDT, PI, PS, ZS…) — draw box around circle + text |
| `inst_cv` | Control/shutdown valve symbol (FCV, XV) — full symbol including actuator |
| `inst_solenoid` | Solenoid box/coil (FY, XY) |

---

## Project Structure

```
qong_product/
├── webapp/             # FastAPI web application
├── pipeline.py         # Main orchestrator (PDF → CSV)
├── extractor.py        # OpenRouter Vision API calls
├── parser.py           # Tag + line number parsing
├── corrections.py      # Manual overrides per drawing
├── validator.py        # Validation + CSV output
├── prompts.py          # All AI prompt templates
├── instrument_parser.py        # Instrumentation index parser
├── instrument_datasheet.py     # Per-instrument HTML datasheets
├── detector.py         # Offline YOLO+OCR detector (training use only)
├── train.py            # YOLO model training script
├── annotate/           # Label Studio data + annotation scripts
├── datasets/           # YOLO training dataset
├── models/             # Trained ONNX model
├── nginx/              # nginx config
├── docker-compose.yml  # All services defined here
└── .env                # Your local secrets (never commit this)
```

---

## Troubleshooting

**Docker build fails on first run**  
Make sure Docker Desktop is fully started (whale icon steady), then retry.

**"OPENROUTER_API_KEY not set" error**  
Check your `.env` file exists and has the key. Restart: `docker compose restart web`

**Jobs stuck in "processing" after restart**  
This is normal — the app resets them to "failed" on startup. Just re-run the job.

**Label Studio shows 500 error after login**  
Run this fix:
```bash
docker compose exec label-studio bash -c "cd /label-studio/label_studio && python3 -c \"
import django, os, sys; sys.path.insert(0, '.'); os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.label_studio'; django.setup()
from users.models import User; from organizations.models import Organization
u = User.objects.get(email='tnb@qongsystems.com'); org = Organization.objects.get(id=1)
org.created_by = u; org.save(); print('Fixed')
\""
```

**Port already in use**  
Another process is using port 8000 or 9000. Stop it or change the port mapping in `docker-compose.yml`.

---

## Getting Help

Ask your team lead or check `CLAUDE.md` for full technical documentation.
