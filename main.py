from fastapi import FastAPI
from routes import shopify_auth, shopify_webhooks

app = FastAPI()
app.include_router(shopify_auth.router)
app.include_router(shopify_webhooks.router)