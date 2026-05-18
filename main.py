from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import requests
from requests.exceptions import RequestException
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("OrderServiceDeployed")
# DATABASE_URL = os.getenv("OrderServiceLocal")

PRODUCT_SERVICE = "https://dc-cep-product-service-production-f1dc.up.railway.app"
# PRODUCT_SERVICE = "http://localhost:8002"

USER_SERVICE = "https://dc-cep-user-service-production-37e1.up.railway.app"
# USER_SERVICE = "http://localhost:8001"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL_Local = DATABASE_URL
engine = create_engine(DATABASE_URL_Local)


class OrderItem(BaseModel):
    product_id: int = Field(example=1)
    quantity: int = Field(gt=0, example=2)


class OrderCreate(BaseModel):
    user_id: int = Field(example=1)
    items: List[OrderItem]


@app.get("/orders")
def get_orders():

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM Orders"))
            orders = [dict(row._mapping) for row in result]

        return orders

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Database error while fetching orders"
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unexpected server error"
        )


# Create Order
@app.post("/orders")
def create_order(order: OrderCreate):

    try:
        user_id = order.user_id
        items = order.items

        total_amount = 0
        order_items = []

        for item in items:

            product_id = item.product_id
            quantity = item.quantity

            try:
                response = requests.get(
                    f"{PRODUCT_SERVICE}/products/{product_id}",
                    timeout=5
                )

                response.raise_for_status()

                product = response.json()

            except RequestException:
                raise HTTPException(
                    status_code=503,
                    detail="Product service unavailable"
                )

            if "error" in product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {product_id} not found"
                )

            price = product["price"]
            total_amount += price * quantity

            order_items.append({
                "product_id": product_id,
                "quantity": quantity,
                "price": price
            })

        with engine.connect() as conn:

            result = conn.execute(text("""
                INSERT INTO Orders (user_id, total_amount, status)
                OUTPUT INSERTED.order_id
                VALUES (:user_id, :total_amount, 'Pending')
            """), {
                "user_id": user_id,
                "total_amount": total_amount
            })

            order_id = result.fetchone()[0]

            for item in order_items:

                conn.execute(text("""
                    INSERT INTO OrderItems 
                    (order_id, product_id, quantity, price)
                    VALUES 
                    (:order_id, :product_id, :quantity, :price)
                """), {
                    "order_id": order_id,
                    **item
                })

            conn.commit()

        return {
            "order_id": order_id,
            "total_amount": total_amount
        }

    except HTTPException as e:
        raise e

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Database error while creating order"
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unexpected server error"
        )