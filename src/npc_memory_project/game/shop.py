"""Shop catalogue and transaction rules.

Pure logic: prices, stock checks and purchases operate on plain data so they can
be tested, and so the UI layer only has to render the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Item:
    item_id: str
    name: str
    price: int
    description: str
    sold_by: Tuple[str, ...] = ()      # npc ids that stock it


CATALOGUE: Tuple[Item, ...] = (
    Item("medicine", "Restorative Tincture", 24,
         "Mira's own blend. Restores vigour.", ("mira",)),
    Item("bandage", "Linen Bandage", 6,
         "Cheap, clean, and always useful.", ("mira",)),
    Item("herbs", "Dried Herbs", 3,
         "Bitter. Smells of the apothecary.", ("mira",)),
    Item("apple", "Red Apple", 4,
         "Bruised but sweet.", ("arun",)),
    Item("bread", "Warm Loaf", 7,
         "Still warm from the oven.", ("arun",)),
    Item("rumour", "A Rumour", 2,
         "Arun will tell you what the stalls are saying.", ("arun",)),
    Item("receipt", "Pharmacy Receipts", 0,
         "Stamped proof of purchase, dated before the theft.", ()),
)

ITEMS_BY_ID: Dict[str, Item] = {item.item_id: item for item in CATALOGUE}


@dataclass
class Wallet:
    gold: int = 40
    items: Dict[str, int] = field(default_factory=dict)

    def has(self, item_id: str, count: int = 1) -> bool:
        return self.items.get(item_id, 0) >= count

    def add(self, item_id: str, count: int = 1) -> None:
        self.items[item_id] = self.items.get(item_id, 0) + count

    def remove(self, item_id: str, count: int = 1) -> bool:
        if not self.has(item_id, count):
            return False
        self.items[item_id] -= count
        if self.items[item_id] <= 0:
            del self.items[item_id]
        return True

    def total_items(self) -> int:
        return sum(self.items.values())


@dataclass(frozen=True)
class Offer:
    item: Item
    price: int
    discounted: bool
    affordable: bool
    in_stock: bool

    @property
    def available(self) -> bool:
        return self.affordable and self.in_stock


@dataclass(frozen=True)
class PurchaseResult:
    ok: bool
    message: str
    price_paid: int = 0


#: Flat discount applied when the NPC's decision engine picks ``offer_discount``.
DISCOUNT_RATE = 0.25


def price_for(item: Item, *, discount: bool = False) -> int:
    if not discount:
        return item.price
    return max(1, int(round(item.price * (1.0 - DISCOUNT_RATE))))


def build_offers(
    vendor_id: str,
    wallet: Wallet,
    npc_inventory: Dict[str, int],
    *,
    discount: bool = False,
) -> List[Offer]:
    """Offers a vendor can make right now, with affordability/stock resolved."""
    offers: List[Offer] = []
    for item in CATALOGUE:
        if vendor_id not in item.sold_by:
            continue
        price = price_for(item, discount=discount)
        in_stock = npc_inventory.get(item.item_id, 0) > 0
        offers.append(Offer(
            item=item,
            price=price,
            discounted=discount,
            affordable=wallet.gold >= price,
            in_stock=in_stock,
        ))
    return offers


def buy(
    offer: Offer,
    wallet: Wallet,
    npc_inventory: Dict[str, int],
) -> PurchaseResult:
    """Execute a purchase, mutating wallet and vendor stock on success."""
    if not offer.in_stock:
        return PurchaseResult(False, f"{offer.item.name} is out of stock.")
    if wallet.gold < offer.price:
        short = offer.price - wallet.gold
        return PurchaseResult(False, f"Not enough coin — {short} gold short.")
    if npc_inventory.get(offer.item.item_id, 0) <= 0:
        return PurchaseResult(False, f"{offer.item.name} is out of stock.")

    wallet.gold -= offer.price
    wallet.add(offer.item.item_id)
    npc_inventory[offer.item.item_id] = npc_inventory.get(offer.item.item_id, 0) - 1
    if npc_inventory[offer.item.item_id] <= 0:
        del npc_inventory[offer.item.item_id]

    suffix = " (discount applied)" if offer.discounted else ""
    return PurchaseResult(True, f"Bought {offer.item.name} for {offer.price} gold.{suffix}",
                          price_paid=offer.price)
