from core.shops import Shops

shops = Shops().get_ready_shops()

for shop in shops:
    shop.client.register_webhooks(app_url_override='https://app.shreddedtreat.co.uk')