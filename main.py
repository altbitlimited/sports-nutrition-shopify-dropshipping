from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from routes import shopify_auth, shopify_webhooks

app = FastAPI()

# Define the base directory
BASE_DIR = Path(__file__).resolve().parent

# Mount the static directory
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Route for the root URL
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    query_params = dict(request.query_params)
    shop = query_params.get("shop")
    hmac = query_params.get("hmac")
    timestamp = query_params.get("timestamp")

    # If all required params are present, redirect to install
    if shop and hmac and timestamp:
        return RedirectResponse(url=f"/auth/shopify/install?shop={shop}")

    # Otherwise, show your landing page with centered logo
    return templates.TemplateResponse("index.html", {"request": request})

app.include_router(shopify_auth.router)
app.include_router(shopify_webhooks.router)