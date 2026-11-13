# Labo 06 – Réponses aux questions 1 à 3

## Question 1

C'est le fichier `src/controllers/order_saga_controller.py` qui représente la machine à états du document arc42. Sa méthode `run()` contient une boucle `while` qui continue tant que l'état terminal (`END`) n'est pas atteint. Chaque branche `if/elif` correspond à un état du diagramme, et chaque handler retourne l'état suivant :

```python
while self.current_saga_state is not OrderSagaState.END:
    if self.current_saga_state == OrderSagaState.START:
        self.logger.debug("État initial")
        self.current_saga_state = self.create_order_handler.run()
    elif self.current_saga_state == OrderSagaState.ORDER_CREATED:
        self.decrease_stock_handler = DecreaseStockHandler(self.create_order_handler.order_id, order_data['items'])
        self.current_saga_state = self.decrease_stock_handler.run()
    elif self.current_saga_state == OrderSagaState.STOCK_DECREASED:
        self.create_payment_handler = CreatePaymentHandler(self.create_order_handler.order_id, order_data)
        self.current_saga_state = self.create_payment_handler.run()
    ...
```

Les états eux-mêmes sont définis dans l'énumération `OrderSagaState` (`START`, `ORDER_CREATED`, `STOCK_DECREASED`, `PAYMENT_CREATED`, `STOCK_INCREASED`, `ORDER_DELETED`, `END`). Ils correspondent aux états numérotés du diagramme.

L'implémentation n'est pas complète. Dans le diagramme, la transition `STOCK_INCREASED → ORDER_DELETED` se fait par l'action `DeleteOrder`. Dans le contrôleur, cette transition n'est pas implémentée : il y a seulement un `TODO`, et l'état passe directement à `ORDER_DELETED` sans que la commande soit réellement supprimée :

```python
elif self.current_saga_state == OrderSagaState.STOCK_INCREASED:
    self.logger.debug("TODO: implémentez et utilisez la classe DeleteOrderHandler et ensuite changez à l'état ORDER_DELETED")
    self.current_saga_state = OrderSagaState.ORDER_DELETED
```

Il manque donc le handler `DeleteOrderHandler`. Il n'est ni importé ni instancié dans le contrôleur, contrairement aux trois autres handlers :

```python
from handlers.create_order_handler import CreateOrderHandler
from handlers.decrease_stock_handler import DecreaseStockHandler
from handlers.create_payment_handler import CreatePaymentHandler
# DeleteOrderHandler absent
```

Ainsi, dans le chemin de compensation qui suit un échec du paiement, la commande resterait dans la base de données du Store Manager, même si la saga indique qu'elle a été supprimée.

## Question 2

Non. `CreateOrderHandler` ne se connecte à aucune base de données. Il n'importe ni SQLAlchemy, ni MySQL, ni Redis. Il crée la commande en envoyant une requête HTTP au Store Manager, en passant par l'API Gateway (KrakenD) :

```python
import config
import requests
...
response = requests.post(f'{config.API_GATEWAY_URL}/store-manager-api/orders',
    json=self.order_data,
    headers={'Content-Type': 'application/json'}
)
if response.ok:
    data = response.json()
    self.order_id = data['order_id'] if data else 0
    self.logger.debug("Transition d'état: CreateOrder -> ORDER_CREATED")
    return OrderSagaState.ORDER_CREATED
```

L'adresse du gateway vient de la configuration (`.env`) :

```
API_GATEWAY_URL=http://api-gateway:8080
```

L'accès à la base de données est fait par le Store Manager lui-même, qui est le seul propriétaire de ses données. Dans `log430-labo5`, c'est la commande `add_order` qui ouvre une session SQLAlchemy :

```python
# log430-labo5/src/orders/commands/write_order.py
def add_order(user_id: int, items: list):
    ...
    session = get_sqlalchemy_session()
```

L'orchestrateur ne fait que coordonner les services par des appels REST, conformément au patron Saga orchestré et au principe « une base de données par service ».

## Question 3

`CreateOrderHandler` appelle `POST /store-manager-api/orders` sur KrakenD. Dans `config/krakend.json`, cet endpoint redirige vers `POST /orders` du Store Manager :

```json
{
  "endpoint": "/store-manager-api/orders",
  "method": "POST",
  "input_headers": ["*"],
  "backend": [
    {
      "url_pattern": "/orders",
      "host": ["http://store_manager:5000"],
      "timeout": "5s"
    }
  ]
}
```

Cela correspond à la requête **`/orders` (POST)** de la collection Postman du Labo 05 (`docs/collections/store_manager.json`) :

```
POST {{baseURL}}/orders        (baseURL = localhost:5000)
{
    "user_id": 1,
    "items": [{"product_id": 1, "quantity": 2}]
}
```

Le corps a le même format que `order_data`, que le handler envoie :

```python
order_data = {
    "user_id": payload.get('user_id'),
    "items": payload.get('items', [])
}
```

Côté Store Manager, l'endpoint est défini dans `store_manager.py` :

```python
@app.post('/orders')
def post_orders():
    """Create a new order based on information on request body"""
    return create_order(request)
```

La seule différence est le chemin d'accès. Postman appelle le Store Manager directement (`localhost:5000/orders`), alors que l'orchestrateur, qui roule dans Docker, passe par le gateway (`http://api-gateway:8080/store-manager-api/orders`).

<!-- TODO: ajouter une capture d'écran de la requête POST /orders dans Postman (méthode, URL, onglet Body) -->
