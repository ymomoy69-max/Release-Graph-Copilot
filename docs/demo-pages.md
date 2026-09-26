# Demo speaking script

Show the pages in this order. On Readiness, click **Scan workspace & sync** for the E-Commerce workspace before you rely on the later pages. The scan is what puts the three shop bugs on the graph, the Fix PR board, and the deploy gate.

## Acme Shop

This is Acme Shop, the store the team is actually shipping, at port 8082. The catalog loads from product-service, and Place order walks through the gateway into order-service, which reserves stock, charges payment-service, and then emails the buyer. Checkout can still succeed, which is the point: the three bugs are in the service code, not in this button. Open the payment file and there is a live API token written in source, `PAYMENT_API_TOKEN`. In order-service the notification call ends with `except Exception: pass`, so a failed email disappears and the order still looks confirmed. In inventory-service the warehouse client is `httpx.Client()` with no timeout, so a hung supplier can stall every reserve behind it. The Incident simulation buttons are a separate live failure: Enable payment failure makes the next checkout return an error, and Restore payments brings it back.

## Sign in

Sign in is only the door. Use admin@acme.demo and admin123!. The account does not invent the bugs or the graph. After this, every number on the next pages comes from the E-Commerce workspace on disk and, when the shop is running, from the live payment health check.

## Readiness

Readiness is where the workspace becomes the product. The folder is the ecommerce demo. Scan workspace and sync walks the services on disk and files what it can prove. It should report three issues. payment-service, services/payment/app.py, a hardcoded token, which is high and blocks deploy. order-service, services/order/app.py, an exception that is caught and ignored, so the confirmation email can fail while checkout still looks fine. inventory-service, services/inventory/app.py, an HTTP client with no timeout, so a slow warehouse holds the callers. Each card is the engine’s file, line, and fix. A person still has to review them on Fix PRs. That same scan refreshes the graph and opens the tickets.

## Home

Home is the snapshot after that scan. The strip is the live count: three scanner issues, open incidents, open Fix PRs, breaking links, and whether shop payments are healthy or failure mode is on. Production risk is scored again on each refresh from those findings, not from a label someone typed. The deploy gate stays blocked because the payment token is still in the file. The other two findings are real, and the token is the one that keeps a production deploy shut. If those counts are empty, the scan on Readiness has not been run yet.

## Release Graph

The Release Graph is who calls whom. Click payment-service and the box is red because of the hardcoded token: anyone with the repo can use that credential, and the services that charge through it are the blast radius. Click order-service and the finding is the swallowed exception, so callers can think the order finished when the notification never left. Click inventory-service and the finding is the client with no timeout; if that call hangs, reserve hangs, and order-service waits on it. A red arrow is a breaking link from the scan. What can be affected is computed from those dependencies. What would change is the engine fix: move the token to the environment, let the notification error surface, and set a timeout so checkout fails fast instead of stalling.

## Fix PRs

Fix PRs is the human review board for those three findings. Each ticket names the file and line, the service, who it affects, and the engine fix. The payment ticket says to load the token from the environment and rotate it. The order ticket says to log the error and return a real failure instead of `pass`. The inventory ticket says to set a timeout and fail fast. Approve means a person agrees the bug is real. It does not edit the file. Re-scan and close only drops the ticket when that line is gone from disk. Copilot cannot approve or close these.

## Incidents

Incidents is the on-call board. The scan opens a code ticket per finding, tied to payment-service, order-service, or inventory-service, with the file story in the timeline. Open one and you see the same bug the graph marked, plus who else feels it. Separately, Run a failing checkout turns payment failure on in the live shop, places one order, and files a checkout ticket from the gateway error. That ticket is the storefront failure. It closes after you restore payments on the shop and sync. It is not the hardcoded token. Analyze files, impact, and fixes reads the workspace again and lists those same engine findings.

## Copilot

Copilot answers from tools on this project, then shows the proof underneath. Ask what scanner issues block deploy, and the answer should name the payment token, because that finding is high. Ask what is wrong, which file, and what the fix is, and it should stay on the three lines: the token in payment-service, the swallowed exception in order-service, and the inventory client with no timeout. Ask what breaks if payment-service fails, and it uses the same graph: order-service and the storefront cannot finish a charge. It can rephrase the evidence. It does not invent a file, and it cannot approve a Fix PR.

## Releases

Releases is the train: what is in production, what is next, and whether deploy is allowed. After the scan, deploy stays blocked while the payment token is still in source. The swallowed exception and the missing timeout are on the board too, and the gate treats the hardcoded secret as the blocker. Start next release only when the train allows it. Opening a version shows the risk score, the services in that release, and the factors behind the score, including the open scanner findings.

## Release detail

This is one version. The status, environment, and risk score come from the engine. Services in this release are the shop services you just traced. Deploy to production stays unavailable while the payment token is in the workspace, and the banner lists the blocking finding. Rollback, when this version is the live one, returns production to the baseline. It is a real release record, not a label change. Commits and CI show here when that version has them.

## Audit log

The audit log is the receipt. After this walk it should show the workspace scan, the readiness check, any failing checkout you ran, and the Copilot question. Human means someone signed in and clicked. AI means Copilot recorded an ask. It does not write to GitHub. It is how you show who scanned the three bugs and who asked about them.
