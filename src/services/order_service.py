from typing import Literal, Optional

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from src.helpers.clob_client import create_clob_client


def get_market(condition_id: str) -> dict:
    client = create_clob_client()
    return client.get_market(condition_id=condition_id)


def place_limit_order(
    token_id: str,
    side: Literal['BUY'] | Literal['SELL'],
    price: float,
    size: int,
) -> dict:
    client = create_clob_client()
    constant_side: int
    if side == 'BUY':
        constant_side = BUY
    else:
        constant_side = SELL

    order_args = OrderArgs(
        price=price,
        size=size,
        side=constant_side,
        token_id=token_id,
    )
    signed_order = client.create_order(order_args)
    # Per docs, post with an explicit time-in-force (e.g., GTC)
    resp = client.post_order(signed_order, OrderType.GTC)
    return resp


