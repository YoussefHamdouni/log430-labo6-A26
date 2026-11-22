# Labo 06 – Réponse à la question 4

## Question 4

> Quel endpoint avez-vous appelé pour modifier le stock ? Quelles informations de la commande avez-vous utilisées ?

### Endpoint appelé

`DecreaseStockHandler` appelle **`PUT /store-manager-api/stocks`** sur KrakenD (`config.API_GATEWAY_URL`, soit `http://api-gateway:8080` dans Docker). Comme pour `CreateOrderHandler`, l'orchestrateur ne parle jamais directement au Store Manager : c'est KrakenD qui achemine la requête vers `PUT /stocks` du Store Manager (`config/krakend.json` de `log430-labo5`, branche `labo6-setup`) :

```json
{
  "endpoint": "/store-manager-api/stocks",
  "method": "PUT",
  "input_headers": ["*"],
  "backend": [
    {
      "url_pattern": "/stocks",
      "host": ["http://store_manager:5000"],
      "timeout": "5s"
    }
  ]
}
```

Côté Store Manager, `PUT /stocks` appelle `update_stock()`, qui applique une opération `+` ou `-` à chaque article (`src/store_manager.py` et `src/stocks/controllers/stock_controller.py`) :

```python
@app.put('/stocks')
def put_stocks():
    """Check in/out product stock for given product_id and quantity"""
    return update_stock(request)

def update_stock(request):
    """Update stock quantities of a product based on given operation (+/-)"""
    payload = request.get_json() or {}
    items = payload.get('items')
    operation = payload.get('operation')
    ...
    update_stock_mysql(session, items, operation)   # UPDATE stocks SET quantity = quantity - :qty WHERE product_id = :pid
```

Il ne faut pas utiliser `POST /stocks`, même si le commentaire du gabarit le suggère et que c'est la seule requête de stock dans la collection Postman du Labo 05 : `POST /stocks` appelle `set_stock()`, qui **remplace** la quantité d'un seul produit par une valeur absolue (`{"product_id": 1, "quantity": 56}`). Pour une saga, il faut au contraire **retirer** les quantités commandées, pour pouvoir les **remettre** lors de la compensation (`operation: "+"`, activité 3).

### Informations de la commande utilisées

- **`run()`** utilise la liste des articles de la commande (`self.order_item_data`, c'est-à-dire `order_data['items']` reçu par l'orchestrateur), avec le `product_id` et la `quantity` de chaque article, et l'opération `"-"` :

```python
def run(self):
    """Call StoreManager to check out from stock"""
    try:
        # PUT /stocks (et non POST, qui fixe une quantité absolue) retire les quantités de chaque article
        response = requests.put(f'{config.API_GATEWAY_URL}/store-manager-api/stocks',
            json={
                "items": self.order_item_data,
                "operation": "-"
            },
            headers={'Content-Type': 'application/json'}
        )
        if response.ok:
            self.logger.debug("Transition d'état: DecreaseStock -> STOCK_DECREASED")
            return OrderSagaState.STOCK_DECREASED
        else:
            self.logger.error(f"DecreaseStock a échoué : {response.status_code} - {response.text}")
            return self.rollback()

    except Exception as e:
        self.logger.error("DecreaseStock a échoué : " + str(e))
        return self.rollback()
```

- **`rollback()`** utilise l'**`order_id`** retourné par `CreateOrderHandler` : si le stock ne peut pas être diminué, on compense l'étape précédente en supprimant la commande avec `DELETE /store-manager-api/orders/{order_id}`. C'est la transition `DecreaseStockFailure → ORDER_DELETED` du diagramme de machine à états. Si la suppression échoue elle-même, on l'enregistre dans les logs et on passe quand même à l'état suivant (pas de rollback sur les rollbacks) :

```python
def rollback(self):
    """ Call StoreManager to delete order if stock decrease fails """
    # Compensation de CreateOrder : la commande est supprimée, car le stock n'a pas pu être réservé
    try:
        response = requests.delete(f'{config.API_GATEWAY_URL}/store-manager-api/orders/{self.order_id}')
        if not response.ok:
            self.logger.error(f"La suppression de la commande {self.order_id} a échoué : {response.status_code} - {response.text}")
    except Exception as e:
        self.logger.error(f"La suppression de la commande {self.order_id} a échoué : " + str(e))

    # Même si la compensation échoue, on passe à l'état suivant (pas de rollback sur les rollbacks)
    self.logger.debug(f"Transition d'état: DecreaseStockFailure -> ORDER_DELETED")
    return OrderSagaState.ORDER_DELETED
```

Le `user_id` et le montant ne sont pas nécessaires pour cette étape : ils servent seulement à créer la commande (étape 1) et le paiement (étape 3).

### Vérification

**Flux normal** : `POST /saga/order` avec `{"user_id": 1, "items": [{"product_id": 2, "quantity": 3}]}`. Les logs de l'orchestrateur suivent exactement le diagramme :

```txt
Controller - DEBUG - État initial
Handler - DEBUG - Transition d'état: CreateOrder -> ORDER_CREATED
Handler - DEBUG - Transition d'état: DecreaseStock -> STOCK_DECREASED
Handler - DEBUG - Transition d'état: CreatePayment -> PAYMENT_CREATED
Controller - DEBUG - Transition à l'état terminal
"POST /saga/order HTTP/1.1" 200 -
```

Et le Store Manager reçoit bien les deux appels, à travers KrakenD :

```txt
"POST /orders HTTP/1.1" 201 -
"PUT /stocks HTTP/1.1" 201 -
```

**Échec et compensation** : on force un échec de `PUT /stocks` en envoyant un article sans `quantity` (le Store Manager répond 500). Le handler appelle `rollback()`, qui supprime la commande 2 :

```txt
Handler - DEBUG - Transition d'état: CreateOrder -> ORDER_CREATED
Handler - ERROR - DecreaseStock a échoué : 500 -
Handler - DEBUG - Transition d'état: DecreaseStockFailure -> ORDER_DELETED

# Store Manager
"DELETE /orders/2 HTTP/1.1" 200 -

mysql> SELECT id FROM orders;
1          -- la commande 2 n'existe plus
```
