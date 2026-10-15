# The stdout Social Contract

*Draft for ratification at the Founding Assembly. Nothing here is binding until the Assembly adopts it.*

stdout Network is an open source, privacy-first ad network for developer terminals, bought through AdCP. It is built and run by its members as a confederation of small, self-governing communes. This contract is our constitution. It changes rarely, and only by the whole Assembly.

The structure borrows from **democratic confederalism**: power sits in small local units, rises through delegates who can be recalled, is shared by co-chairs rather than held by one person, and serves the commons rather than an owner. We adopt the organising ideas, not any party or movement.

The [Charter](CHARTER.md) says why we exist and how we treat each other. This contract is the machinery that protects it. If the two ever disagree, the Charter wins and this contract is amended to match.

## 1. Principles

1. **Power starts at the bottom.** Communes decide everything inside their own scope. Nothing is decided higher up that can be decided lower down.
2. **Nobody leads alone.** Every commune and the Council has two co-chairs.
3. **Delegates, not representatives.** Delegates carry their commune's position and can be recalled at any time.
4. **One member, one vote.** Employers, sponsors and advertisers have no votes.
5. **Privacy is not negotiable.** No persistent identifiers in ad traffic. Targeting happens on the developer's machine. No proposal that breaks this can pass without amending this contract.
6. **The money serves the commons.** Developers, good causes and the work of the network come before any surplus.
7. **Everything in the open.** Decisions, budgets and payouts are public, except where they would expose an individual.

## 2. Membership

- **Founding members** are the people who sign the [Charter](CHARTER.md) before the Founding Assembly.
- **New members**, in the founding phase, join because an existing member brings them in. They sign the Charter by adding themselves to `MEMBERS.md`, and the member who brought them approves it.
- **Once the Assembly opens the door**, anyone can also join by contributing (code, docs, design, sales, policy, community work) and being welcomed by a commune at its regular meeting. Developers who run `adterm` are especially welcome; it's their terminals.
- There is no fee, and ad tech experience is not required.
- **Members** may vote in the Assembly, stand as co-chair or delegate, and join any commune.
- **Membership lapses** after 12 months with no contribution or attendance. Lapsed members can rejoin the same way anyone joins.
- **Membership ends** only through the Peace and Consensus process (section 8).

## 3. Structure

### Communes

The basic unit. A commune is 3 to 12 members who own one part of the project: its code, its decisions and its roadmap. Communes meet at least fortnightly, keep public notes, and govern themselves however they like within this contract. When a commune grows past 12 it splits; when it falls below 3 it merges or dissolves. The initial communes are listed in [COMMUNES.md](COMMUNES.md).

### The Confederal Council

The two co-chairs of every commune sit on the Council as delegates. The Council coordinates work that crosses communes, holds the budget between Assemblies, and speaks for the project externally when a single voice is needed. It cannot overrule a commune inside that commune's scope; only the Assembly can.

### The General Assembly

All members. Meets at least quarterly, online, with asynchronous voting open for 7 days. The Assembly amends this contract, sets the revenue splits, approves the annual budget, creates or dissolves communes, and elects the Peace and Consensus Committee.

## 4. Co-chairs

- Every commune and the Council has **two co-chairs** who share the role equally. Neither outranks the other.
- **Balance rule (to ratify, ballot 2):** the model this structure borrows from requires every co-chair pair to include at least one woman. The Founding Assembly chooses between that strict rule and a softer "gender-balanced where the commune can" version, and may extend either to explicitly include non-binary members.
- **Terms** are 6 months, with at most 2 consecutive terms in the same seat.
- **Recall:** a commune can recall either co-chair at any time by a simple majority of its members.

## 5. Decisions

We decide at the lowest level that can, as lightly as possible, and escalate only when we must.

| Level | Used for | How |
|---|---|---|
| Do-ocracy | Anything inside one commune's scope | Whoever does the work decides, following commune norms |
| Lazy consensus | Changes touching another commune | Post the proposal; it passes after 72 hours without a blocking objection |
| RFC | Cross-cutting design, policy, new products | Written proposal, 7 days of discussion, consensus sought; if blocked, Council vote |
| Council vote | Operational matters and budget between Assemblies | Simple majority of delegates, quorum of two thirds |
| Assembly vote | This contract, revenue splits, licence, legal home, communes | Two thirds of votes cast, quorum of one third of members |

A **blocking objection** must say what principle or harm it protects against and what would resolve it. "I don't like it" is a concern, not a block.

## 6. Guarding against capture

Ad tech is a small world, so:

- **No more than one third of Council delegates** may share an employer. If a vote would breach this, the commune picks a different delegate.
- **Members declare** their employer and any commercial interest in a decision before voting on it, and abstain where the interest is direct.
- **Advertisers, sponsors and buyers** get a voice through the Market commune and RFCs, never a vote.
- **No member or company** may hold exclusive rights to the name, the code or the network.

## 7. The social economy

Money from advertisers is split by rules the Assembly sets, not by anyone's discretion. The Founding Assembly ratifies the starting numbers.

| Allocation | Proposed starting rule |
|---|---|
| Developers who run `adterm` | 70% of gross revenue from rendered paid ads, paid to the developer, an open source project, or a charity of their choice |
| Ads for good | 20% of impressions reserved for verified charities, free of charge |
| The network | The remaining 30% of revenue covers hosting, payout fees, fraud controls and legal costs |
| The fighting fund | 10% of profit, held back for members who lose their jobs |
| Beer and marketing | Everything left after that, split between gatherings and marketing as the Assembly decides each year (proposed: half each) |

**Profit** means the network's 30% minus its actual costs in the period. If there is no profit, nothing goes to the fighting fund, the beer or the marketing, and nobody is owed anything.

Payout and charity flows are published monthly in aggregate. Individual earnings are never published.

### The fighting fund

Ad tech lays people off in waves. The fighting fund is how the confederation looks after its own when that happens.

- **Who:** any member of at least 3 months' standing who loses paid work, for any reason.
- **What:** a one-off grant, at most a quarter of the fund's balance at the time, and at most one grant per member per 12 months.
- **How:** the member writes privately to the fund panel: the two Treasury co-chairs plus one member of the Peace and Consensus Committee. The panel decides within 7 days, by majority, and nobody else learns who asked.
- **Discretionary:** grants are gifts of solidarity, not insurance, wages or an entitlement. The fund promises nothing and pays only what it holds.
- **Ceiling:** if the fund ever exceeds a ceiling the Assembly sets (proposed: £10,000), new money flows to beer and marketing instead.
- **Reporting:** the Treasury publishes the number of grants and the total paid each quarter, never names.

Money is the smallest part of it. A member who loses their job can also post to the solidarity channel, and every member is asked to share leads, make introductions and give references. Sixty people across ad tech is a better job network than most recruiters.

## 8. Peace and Consensus

Disputes and Code of Conduct reports go to the **Peace and Consensus Committee**: 3 to 5 members elected by the Assembly for 6 months, who may not sit on the Council at the same time. The Committee works restoratively first, meaning it aims to repair harm and keep people in the project, and can escalate to suspension or removal when needed. Removal of a member requires the Committee's unanimous recommendation and is reviewable by the Assembly. Details are in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## 9. Autonomy and federation

Any group may fork the code; the licence guarantees it. A fork that adopts this contract and its privacy principles can apply to the Assembly to **federate**: its communes send delegates to our Council, and the two networks can share inventory and buyers. The confederation grows by joining, not by absorbing.

## 10. Amendments

This contract changes only by an Assembly vote of two thirds of votes cast, with a quorum of one third of members, after the proposal has been public for at least 14 days. Section 1 principle 5 (privacy) additionally requires that no Assembly member votes against it, or that it passes at two consecutive Assemblies.
