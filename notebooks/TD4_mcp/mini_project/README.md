# Mini-projet — PIM MCP server (stdio)

Ce dossier contient un serveur MCP **autonome**, en **stdio** (out-of-process), qui expose
le même catalogue PIM que le notebook, mais avec un index ChromaDB **persistant**.

## Fichiers

- `pim_server.py` — le serveur MCP. 6 tools :
  - `search_products(query, k=3)` — RAG sémantique (TD3), sur l'index persistant
  - `get_product(sku)` — lecture exacte d'un produit
  - `get_category_tree()`
  - `get_category_attributes(category)`
  - `create_product(...)` — écriture : embed + `collection.add(...)`, immédiatement recherchable
  - `delete_product(sku)` — bonus "Going further"
- `client_demo.py` — un client stdio minimal qui **spawn** `pim_server.py` comme process séparé
  et appelle chaque tool, pour sentir la frontière out-of-process (contrairement au transport
  in-memory du notebook).

## Prérequis

Le `venv` du repo a déjà tout ce qu'il faut (`mcp`, `chromadb`, `sentence-transformers`, `pandas`).
Active-le avant de lancer quoi que ce soit :

```bash
source ../../../venv/bin/activate   # adapte le chemin si besoin
```

## Tester en local (sans Claude Desktop)

```bash
cd notebooks/TD4_mcp/mini_project
python client_demo.py
```

Ça lance `pim_server.py` en sous-processus, liste les tools découverts, puis appelle
`get_category_tree`, `search_products`, `create_product`, `get_product`, `delete_product`.

Le premier lancement construit l'index ChromaDB persistant dans `mini_project/chroma_store/`
(quelques secondes, une seule fois — les lancements suivants réutilisent l'index existant).

## Enregistrer dans Claude Desktop

Ajoute une entrée dans la config MCP de Claude Desktop
(`claude_desktop_config.json`, menu *Settings → Developer → Edit Config*) :

```json
{
  "mcpServers": {
    "pim": {
      "command": "/chemin/absolu/vers/venv/bin/python",
      "args": ["/chemin/absolu/vers/notebooks/TD4_mcp/mini_project/pim_server.py"]
    }
  }
}
```

Redémarre Claude Desktop, puis pose une question du type :

> "Quels casques anti-bruit on a en dessous de 300€ ?"

Claude Desktop doit découvrir `search_products` (et éventuellement `get_category_attributes`)
et les appeler tout seul.

### Vérifier la fraîcheur end-to-end

Dans la même conversation Claude Desktop :
1. Demande de créer un produit (`create_product`) avec un nom distinctif.
2. Demande immédiatement de le rechercher (`search_products`).
3. Il doit apparaître sans ré-indexation manuelle — c'est le "TD3 freshness aha", maintenant
   exposé comme tool.

## Notes

- Les chemins de données (`../../data/products.csv`, `../../data/taxonomy.json`) sont résolus
  relativement à ce fichier, donc peu importe le dossier depuis lequel tu lances `python`.
- Si tu changes le schéma des produits/attributs, supprime `chroma_store/` pour forcer une
  ré-indexation propre au prochain lancement.
