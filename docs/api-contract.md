# API Contract (Starter)

Base URL examples:
- Production: `https://api.yourbrand.com/v1`
- Staging: `https://staging-api.yourbrand.com/v1`

## Public Endpoints

### `GET /products`
Query params:
- `category`
- `search`
- `minPrice`
- `maxPrice`
- `sort` (`newest`, `priceAsc`, `priceDesc`)
- `page`, `limit`

### `GET /products/:slug`
Returns product, variants, and images.

### `POST /auth/register`
### `POST /auth/login`
### `POST /auth/refresh`

## Cart & Checkout

### `GET /cart`
### `POST /cart/items`
Body:
```json
{
  "variantId": "uuid",
  "quantity": 2
}
```

### `PATCH /cart/items/:id`
### `DELETE /cart/items/:id`

### `POST /checkout/create-order`
Creates order from cart and returns payment intent/order token.

### `POST /payments/webhook`
Gateway server-to-server callback for payment verification.

## Orders

### `GET /orders`
### `GET /orders/:id`

## Admin Endpoints (RBAC)

### `POST /admin/products`
### `PATCH /admin/products/:id`
### `DELETE /admin/products/:id`
### `POST /admin/products/:id/images`
### `PATCH /admin/variants/:id`
### `GET /admin/orders`

## Example Product Response
```json
{
  "id": "uuid",
  "name": "Ivory Embroidered Kurta",
  "slug": "ivory-embroidered-kurta",
  "description": "Handcrafted designer piece",
  "basePrice": 120.00,
  "currency": "USD",
  "images": [
    {"url": "https://cdn.example.com/p1.jpg", "sortOrder": 1}
  ],
  "variants": [
    {
      "id": "uuid",
      "sku": "KURTA-IVORY-M",
      "size": "M",
      "color": "Ivory",
      "price": 120.00,
      "stockQty": 12
    }
  ]
}
```
