# Running Deskpilot locally

A throwaway ERPNext with Deskpilot on it, for evaluating the app, recording a demo,
or taking screenshots against clean data. Everything here is disposable.

## 1. A site

[`frappe_docker`](https://github.com/frappe/frappe_docker) ships a single-command
ERPNext for exactly this. It is not a production setup and is not meant to be.

```bash
git clone https://github.com/frappe/frappe_docker
cd frappe_docker
docker compose -f pwd.yml up -d
docker compose -f pwd.yml logs -f create-site   # wait for it to finish, then Ctrl-C
```

That gives you <http://localhost:8080> — site `frontend`, user `Administrator`,
password `admin`.

## 2. Deskpilot

```bash
docker compose -f pwd.yml exec backend \
  bench get-app --branch main https://github.com/mdad-elec/deskpilot
docker compose -f pwd.yml exec backend \
  bench --site frontend install-app deskpilot
docker compose -f pwd.yml exec backend \
  bench --site frontend migrate
```

Reload the Desk. As Administrator the setup wizard offers itself once.

Apps added to a running container this way do not survive `docker compose down -v`.
That is fine for a demo; it is the reason this is not an install guide.

## 3. Demo data

Stock ERPNext demo data — customers, items, orders — so screenshots show a system
with something in it:

```bash
docker compose -f pwd.yml exec backend \
  bench --site frontend execute erpnext.setup.demo.setup_demo_data
```

It is also offered at the end of ERPNext's own setup wizard. To undo it:
`erpnext.setup.demo.clear_demo_data`.

## 4. A model

The wizard will not move past step one until it has had a real reply, so you need an
endpoint. Cheapest local option:

```bash
ollama pull qwen2.5:7b        # any tool-capable model
ollama serve
```

Then in the wizard: provider **OpenAI-compatible**, base URL
`http://host.docker.internal:11434/v1`, key `not-needed`, model `qwen2.5:7b`.

Note `host.docker.internal` rather than `127.0.0.1` — the endpoint is being called
from inside the container, where localhost is the container.

A hosted API works too, and will be faster and better at following the tool protocol.
Small local models are noticeably worse at emitting actions reliably.

## 5. Knowledge, if you want citations in the shot

Upload a few documents to a folder in the Desk (**Home > Attachments**, or any folder
you create), point **Deskpilot Settings > Knowledge > Frappe folder** at it, and press
*Sync now*. The chunk count it reports is the honest signal that it worked.

## Recording

- Set the browser to 1440×900 or 1280×800. Desk is responsive and a wide window makes
  the assistant panel look lost.
- Light theme reads better in a listing; the mark is dark ink and is designed for it.
- The two things worth showing are the ones prose cannot: the spotlight landing on a
  field, and a walkthrough stepping. Lead with those.
- "Walk me through creating a sales order" is the single best demo prompt.
