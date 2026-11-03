# TradeFlow — AI Trade Log Assistant

TradeFlow helps a fictional Thai equities desk turn informal trade messages into records that a person can review, approve, and trace back to the original instruction.

I built this portfolio project as a third-year Information and Communication Engineering student interested in trading operations, data intelligence, and financial product design. I wanted to answer a practical question: **when a trader corrects a price, how can the desk update its figures and still explain what changed?**

## One trade, two approvals

A trader sends this message:

> Trade T104: bought 100 shares of SAMPLE_A at THB 25.50 on 2026-11-03.

TradeFlow prepares a purchase worth **THB 2,550.00**. The reviewer checks the symbol, quantity, price, and date before approving it. Later, a second message arrives:

> Correct T104: the price should be THB 25.75.

The assistant finds T104 and shows the original and proposed prices side by side. Once the reviewer approves the correction, the trade is worth **THB 2,575.00**. The dashboard’s gross traded value increases by **THB 25.00**, while the trade count stays at seven. The record history preserves both messages and their approval timestamps.

![TradeFlow dashboard showing seven approved trades and THB 21,746.00 in gross traded value](dashboard.jpg)

*The dashboard shows the six sample trades plus T104 after its correction. Gross traded value measures the value of trading activity across buys and sells.*

## What the project demonstrates

| Area | Example from the application |
|---|---|
| **Trading operations** | Two trades can have identical details and both be legitimate. TradeFlow flags the match for review. Reusing an existing trade reference for a new entry blocks approval. |
| **Data intelligence** | Prices are stored in whole satang, the smallest unit of Thai baht. Dashboard totals use the latest approved version of each trade, and each correction can be traced to its source message. |
| **Product design** | If a trader writes “Sold 200 shares of SAMPLE_B today,” the assistant asks for the missing price and currency. The trader can reply “THB 19.80” and confirm the Bangkok date without retyping the original ticket. |
| **AI tool use** | In live mode, the model can look up trades, search for a correction target, prepare a proposal, or ask for clarification. Python validates the proposal, and the reviewer decides whether to save it. |

## What I verified

- **18 automated tests passed.** These include repeated approval clicks, an attempt to overwrite a newer correction, and a failed audit write that requires the whole trade update to roll back.
- **21 synthetic messages were evaluated in the key-free demo.** The demo matched the expected action, clarification decision, tool sequence, and validation outcome on all 21 messages. It also matched all 78 labeled fields. [View the evaluation results](evaluation/demo_results.json).
- **The live API integration was tested with simulated responses.** The tests covered tool calls, malformed output, API failures, and the five-call limit. Accuracy on free-form messages from a live model has not been measured.

<details>
<summary><strong>Try the two-minute demo</strong></summary>

After starting the app, select **Load demo data** to add six trades across four fictional symbols.

1. **Book a trade.** In **Trade Assistant**, select **New trade** and prepare T104. Check the proposed value of THB 2,550.00, then approve it.
2. **Correct the price.** Select **Correction** and compare THB 25.50 with THB 25.75. Approve the change, open **Trade Records**, and search for T104 to see both approvals.
3. **Try an exception.** Select **Duplicate** to see the warning, then discard the ticket. Select **Missing price** and reply `THB 19.80` to complete the proposal.
4. **Check the dashboard.** Leave the last proposal pending. The review queue shows the unfinished ticket, while the activity charts include only approved trades.

</details>

<details>
<summary><strong>Setup and technical details</strong></summary>

**Stack:** Python, Streamlit, SQLite, pandas, Plotly, and the OpenAI Python SDK. The default demo runs locally without an API key and understands the sample English sentence patterns.

With Python 3.12 installed and available as `python`, run these commands from the repository folder in Windows PowerShell:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed in the terminal. On macOS or Linux, use `python3.12 -m venv .venv` and `.venv/bin/python` for the install and launch commands.

**How it works.** The [interface](app.py) handles intake, review, record search, CSV export, and reporting. The [agent](agent.py) and [demo interpreter](demo.py) use the same lookup and proposal tools. The [ledger](ledger.py) saves each approved change and its audit entry in one SQLite transaction. A version check prevents an older proposal from overwriting a newer correction.

**Run the checks** using the project’s Python environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evaluate.py
```

**Optional live mode.** Copy `.env.example` to `.env`, set `TRADEFLOW_MODE=live`, add your `OPENAI_API_KEY`, and restart the app. Each explicit message submission can make up to five API calls. To run a paid evaluation on the synthetic cases, use `evaluate.py --live`.

**Scope.** The prototype uses four fictional THB equities, a local SQLite database, and one pending ticket per browser session. It records synthetic trades and has no brokerage connection or order execution.

</details>
