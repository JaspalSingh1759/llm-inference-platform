"""B2 step 1: builds the labelled dataset for the dispute-type classifier.

Generates Maple Bank dispute claims (what a customer types) with the dispute type as the label,
removes duplicates, splits them into train / validation / test, and writes a manifest whose
hash is the dataset version. Maple Bank is fictional and every record is synthetic.

Same seed + same parameters = same rows = same version, on any machine.

Outputs (in --out)
  train.parquet, val.parquet, test.parquet   the splits
  manifest.json                              version, parameters, counts, file hashes (commit this, not the data)

Usage:
  python generate_claims.py                          # the default training dataset
  python generate_claims.py --fr-share 0.6 --seed 99 --out data/claims-shifted   # a "drifted" batch for step 8
"""

import argparse
import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

LABELS = ["duplicate_charge", "incorrect_amount", "credit_not_processed",
          "cancelled_recurring", "not_received", "unauthorised"]

# name, category, channel, recurring monthly price (None = one-off purchases)
MERCHANTS = [
    ("BestElectro", "electronics", "in_store", None), ("Northern Circuit", "electronics", "in_store", None),
    ("GadgetHub", "electronics", "online", None), ("Lakeshore Grocers", "grocery", "in_store", None),
    ("Marché Saint-Laurent", "grocery", "in_store", None), ("NorthJet Airlines", "airline", "online", None),
    ("Harbourview Hotels", "hotel", "in_store", None), ("Peak Car Rental", "car_rental", "in_store", None),
    ("Maple & Pine Apparel", "apparel", "in_store", None), ("Urban Loft Clothing", "apparel", "in_store", None),
    ("HomeNest Furniture", "furniture", "in_store", None), ("Cedar Hardware", "hardware", "in_store", None),
    ("Bay Street Bistro", "restaurant", "in_store", None), ("Le Petit Café", "restaurant", "in_store", None),
    ("ShopNorth Online", "marketplace", "online", None), ("Coastal Outdoor Gear", "sporting", "in_store", None),
    ("FreshBowl Delivery", "food_delivery", "online", None), ("UrbanRide", "transport", "online", None),
    ("StreamBox", "subscription", "online", 16.99), ("FitNorth Gym", "subscription", "in_store", 59.99),
    ("CloudVault Storage", "subscription", "online", 9.99), ("DailyBrief News", "subscription", "online", 12.00),
    ("Tundra Mobile", "telecom", "online", 75.00),
]
ONE_OFF = [m for m in MERCHANTS if m[3] is None]
RECURRING = [m for m in MERCHANTS if m[3] is not None]
SHIPPABLE = [m for m in ONE_OFF if m[2] == "online" or m[1] in ("furniture", "electronics", "apparel")]
FOREIGN = ["QUICKPAY* ELECTRONICA LISBOA PT", "LUXWATCH OUTLET HK", "FASTTOPUP*CREDIT VILNIUS LT",
           "GIFTCARDPLANET ONLINE", "ATLASTRAVEL*BOOKING"]

AMOUNTS = {"electronics": (25, 1400), "grocery": (18, 210), "airline": (180, 900), "hotel": (140, 520),
           "car_rental": (90, 400), "apparel": (30, 260), "furniture": (150, 1400), "hardware": (12, 180),
           "restaurant": (14, 140), "marketplace": (15, 300), "sporting": (40, 350), "food_delivery": (18, 70),
           "transport": (9, 55)}

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
             "octobre", "novembre", "décembre"]

# Several phrasings per label and language. Some deliberately share words with other labels
# ("refund", "charged", "never") so the classifier has to learn more than one keyword.
TEMPLATES = {
    "duplicate_charge": {
        "en": ["I was charged twice at {m} for the same purchase of {a}.",
               "My statement shows two identical charges of {a} from {m} on {d}. I only bought it once.",
               "{m} billed me {a} two times. Please reverse the duplicate.",
               "Same charge appears twice, {a} at {m}. Can I get one refunded?",
               "Double charge from {m}! {a} posted on {d} and again the next day.",
               "There are 2 transactions for {a} at {m} but I paid once. Receipt attached.",
               "Just noticed I was charged twice at {m} back in {mo}."],
        "fr": ["J'ai été facturé deux fois chez {m} pour le même achat de {a}.",
               "Mon relevé montre deux débits identiques de {a} de {m} le {d}.",
               "{m} m'a débité {a} à deux reprises. Merci d'annuler le doublon.",
               "Le même montant de {a} apparaît deux fois pour {m}. Je n'ai payé qu'une fois.",
               "Double facturation chez {m} en {mo}, {a} chaque fois."],
    },
    "incorrect_amount": {
        "en": ["My receipt from {m} says {a} but my statement shows {a2}. I was overcharged.",
               "{m} charged me {a2} instead of {a}. Receipt attached.",
               "The amount posted by {m} is wrong: I agreed to pay {a}, not {a2}.",
               "I was overcharged by {diff} at {m} in {mo}.",
               "{m}'s receipt says {a} but I was charged {a2}. That's way more than I paid!",
               "Wrong amount on my card from {m} on {d}. It should be {a}."],
        "fr": ["Mon reçu de {m} indique {a} mais mon relevé affiche {a2}.",
               "{m} m'a facturé {a2} au lieu de {a}. Reçu en pièce jointe.",
               "Le montant débité par {m} est incorrect : {a2} au lieu de {a}.",
               "On m'a surfacturé {diff} chez {m} en {mo}."],
    },
    "credit_not_processed": {
        "en": ["I returned my order to {m} on {d} and still haven't received the {a} refund.",
               "{m} promised a refund of {a} weeks ago but it never showed up on my card.",
               "Returned the item to {m}, they gave me a return slip, but no credit yet for {a}.",
               "Where is my refund from {m}? Return was accepted on {d}.",
               "{m} confirmed my return in {mo} but the credit of {a} is missing.",
               "I got a refund confirmation email from {m} for {a} but nothing posted to my account."],
        "fr": ["J'ai retourné ma commande à {m} le {d} et je n'ai toujours pas reçu le remboursement de {a}.",
               "{m} m'a promis un remboursement de {a} mais il n'apparaît pas sur ma carte.",
               "Retour accepté par {m} en {mo}, mais aucun crédit de {a} pour l'instant.",
               "Où est mon remboursement de {m}? Le retour a été confirmé le {d}."],
    },
    "cancelled_recurring": {
        "en": ["I cancelled my {m} subscription on {d} but they kept charging me {p}. Confirmation attached.",
               "{m} is still billing me {p} a month even though I cancelled in {mo}.",
               "Cancelled {m} membership, got a cancellation number, still charged {p}.",
               "I ended my {m} plan last month and was charged again. Please stop these payments.",
               "{m} charged my card {p} after I cancelled. I never renewed.",
               "Recurring charge from {m} continues after cancellation on {d}."],
        "fr": ["J'ai annulé mon abonnement {m} le {d} mais ils continuent de me facturer {p}.",
               "{m} me facture encore {p} par mois alors que j'ai annulé en {mo}.",
               "Abonnement {m} résilié, numéro d'annulation reçu, mais toujours débité de {p}.",
               "Prélèvement récurrent de {m} après mon annulation le {d}."],
    },
    "not_received": {
        "en": ["I ordered from {m} on {d} and it never arrived. Order confirmation attached.",
               "Paid {a} to {m} but the package never came. The seller doesn't answer.",
               "My order from {m} for {a} was never delivered.",
               "{m} took my money ({a}) in {mo} and I never got the goods.",
               "Item from {m} still not delivered, tracking hasn't moved since {d}.",
               "I never received what I bought from {m}. I want my {a} back."],
        "fr": ["J'ai commandé chez {m} le {d} et je n'ai jamais reçu le colis.",
               "J'ai payé {a} à {m} mais la commande n'est jamais arrivée.",
               "Ma commande de {m} n'a jamais été livrée. Le vendeur ne répond pas.",
               "{m} a pris mon argent ({a}) en {mo} et je n'ai rien reçu."],
    },
    "unauthorised": {
        "en": ["There's a charge of {a} from \"{f}\" on my statement. I don't recognise it. Is this fraud?",
               "I see charges I never made on {d}, total {a}. I still have my card. Please help.",
               "Someone used my card at {f} for {a}. It wasn't me.",
               "Unknown transaction {a} from {f}. I have never shopped there.",
               "Fraud! {a} charged on {d} at {f}, I was home all day.",
               "I don't recognise a {a} payment to {f}. Please block my card."],
        "fr": ["Il y a un débit de {a} de « {f} » sur mon relevé. Je ne le reconnais pas.",
               "Je vois des achats que je n'ai jamais faits le {d}, total {a}.",
               "Quelqu'un a utilisé ma carte chez {f} pour {a}. Ce n'était pas moi.",
               "Transaction inconnue de {a} chez {f}. Fraude?"],
    },
}
OPENERS = {"en": ["", "", "", "Hi, ", "Hello, ", "Good morning. "], "fr": ["", "", "", "Bonjour, ", "Allô, "]}
CLOSERS = {"en": ["", "", "", " Thanks.", " Please help.", " Thank you for looking into this."],
           "fr": ["", "", "", " Merci.", " Merci de votre aide."]}

START, END = date(2026, 1, 1), date(2026, 11, 14)


def fmt_money(x, lang):
    return f"{x:,.2f} $".replace(",", " ").replace(".", ",") if lang == "fr" else f"${x:,.2f}"


def fmt_date(d, lang):
    return f"{d.day} {MONTHS_FR[d.month - 1]}" if lang == "fr" else f"{d:%b %d}"


def add_typos(text, rng):
    """Swap two neighbouring letters once or twice, as people do on phones."""
    chars = list(text)
    for _ in range(rng.randint(1, 2)):
        i = rng.randrange(1, len(chars) - 2)
        if chars[i].isalpha() and chars[i + 1].isalpha():
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def make_claim(label, lang, rng):
    if label == "cancelled_recurring":
        merchant = rng.choice(RECURRING)
    elif label == "not_received":
        merchant = rng.choice(SHIPPABLE)
    else:
        merchant = rng.choice(ONE_OFF)
    name, category, channel, monthly = merchant
    lo, hi = AMOUNTS.get(category, (10, 100))
    amount = round(rng.uniform(lo, hi), 2) if monthly is None else monthly
    when = START + timedelta(days=rng.randint(0, (END - START).days))
    wrong = round(amount + rng.choice([5, 10, 20, 25, 50, 100]) + rng.choice([0, 0.99]), 2)
    if label == "unauthorised":
        channel = "online"
        category = "unknown"

    text = rng.choice(TEMPLATES[label][lang]).format(
        m=name, a=fmt_money(amount, lang), a2=fmt_money(wrong, lang), diff=fmt_money(wrong - amount, lang),
        p=fmt_money(amount, lang), d=fmt_date(when, lang),
        mo=MONTHS_FR[when.month - 1] if lang == "fr" else f"{when:%B}", f=rng.choice(FOREIGN))
    text = rng.choice(OPENERS[lang]) + text + rng.choice(CLOSERS[lang])

    # Real input is messy: some customers type in lowercase, some make typos.
    if rng.random() < 0.15:
        text = text.lower()
    if rng.random() < 0.20:
        text = add_typos(text, rng)

    return {"text": text, "language": lang, "merchant_category": category, "channel": channel,
            "amount": amount, "submitted": str(when + timedelta(days=rng.randint(1, 30))), "label": label}


def build(rows, fr_share, label_noise, seed):
    rng = random.Random(seed)
    records = []
    for _ in range(rows):
        record = make_claim(rng.choice(LABELS), "fr" if rng.random() < fr_share else "en", rng)
        # Human labellers make mistakes; a small share of wrong labels keeps the test honest.
        if rng.random() < label_noise:
            record["label"] = rng.choice([l for l in LABELS if l != record["label"]])
        records.append(record)
    df = pd.DataFrame(records)

    # The same text in train and test would let the model "remember" answers: drop exact duplicates
    # (ignoring case and spaces) before splitting.
    key = df["text"].str.lower().str.split().str.join(" ")
    before = len(df)
    df = df[~key.duplicated()].reset_index(drop=True)
    print(f"generated {before} rows, removed {before - len(df)} duplicates, kept {len(df)}")

    df.insert(0, "claim_id", [f"CLM-{i + 1:06d}" for i in range(len(df))])
    return df


def split(df, seed, val=0.15, test=0.15):
    """Stratified split: every label × language group is divided in the same proportions."""
    parts = {"train": [], "val": [], "test": []}
    for _, group in df.groupby(["label", "language"], sort=True):
        group = group.sample(frac=1, random_state=seed)
        n_test, n_val = round(len(group) * test), round(len(group) * val)
        parts["test"].append(group.iloc[:n_test])
        parts["val"].append(group.iloc[n_test:n_test + n_val])
        parts["train"].append(group.iloc[n_test + n_val:])
    return {name: pd.concat(frames).sort_values("claim_id").reset_index(drop=True) for name, frames in parts.items()}


def content_hash(df):
    """Hash of the rows themselves, so the version doesn't depend on the Parquet library version."""
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=6000)
    p.add_argument("--fr-share", type=float, default=0.25, help="share of French claims (0-1)")
    p.add_argument("--label-noise", type=float, default=0.02, help="share of deliberately wrong labels")
    p.add_argument("--seed", type=int, default=20261110)
    p.add_argument("--out", default=str(Path(__file__).parent / "data" / "claims"))
    args = p.parse_args()

    df = build(args.rows, args.fr_share, args.label_noise, args.seed)
    splits = split(df, args.seed)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, part in splits.items():
        part.to_parquet(out / f"{name}.parquet", index=False)
        files[name] = {"rows": len(part), "sha256": content_hash(part)}

    version = hashlib.sha256("".join(files[n]["sha256"] for n in ("train", "val", "test")).encode()).hexdigest()[:12]
    manifest = {
        "dataset": "maple-bank-dispute-claims",
        "version": version,
        "generator": "mlops/data-pipeline/generate_claims.py",
        "parameters": {"rows": args.rows, "fr_share": args.fr_share, "label_noise": args.label_noise, "seed": args.seed},
        "labels": LABELS,
        "files": files,
        "label_counts": df["label"].value_counts().sort_index().to_dict(),
        "language_counts": df["language"].value_counts().sort_index().to_dict(),
        "note": "Maple Bank is fictional. All data is synthetic.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"dataset version {version} → {out}")
    for name in ("train", "val", "test"):
        print(f"  {name:5} {files[name]['rows']:>5} rows")


if __name__ == "__main__":
    main()
