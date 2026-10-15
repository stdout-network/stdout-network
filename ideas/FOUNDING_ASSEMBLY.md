# Founding Assembly

One 90-minute online session, then 7 days of voting. Every open question has a recommended default, so the group only needs to argue about the ones it actually disagrees on.

## One week before

Send everyone:

1. **Sign the [Charter](CHARTER.md)** (4 minutes). Signatories are the founding members, and only they vote.
2. **Read** [SOCIAL_CONTRACT.md](SOCIAL_CONTRACT.md) (10 minutes) and [COMMUNES.md](COMMUNES.md) (2 minutes).
3. **Pick communes:** a form with your first and second choice. The convenors balance them to roughly 6 to 10 per commune.
4. **Suggest amendments** to the Social Contract as comments on the PR, so the session handles a known list rather than ideas from the floor.
5. **Nominate** yourself or others for co-chair seats and the Peace and Consensus Committee.
6. **Suggest names** if you want something other than stdout Network.
7. **Check your employment contract** for IP clauses (see [CONTRIBUTING.md](CONTRIBUTING.md)).

Two convenors run the session as interim co-chairs, and step down when the Council is seated.

## The session (90 minutes)

| Time | Item | Output |
|---|---|---|
| 0 to 10 | Welcome; someone reads the Charter aloud; how voting works | Everyone knows the ballots |
| 10 to 30 | Social Contract walkthrough, pre-submitted amendments, the co-chair balance rule | Final ballot 1 text, ballot 2 framed |
| 30 to 45 | The money: developer share, ads for good, the fighting fund, and the beer | Ballots 4, 5 and 10 framed |
| 45 to 55 | Licence and legal home | Ballots 3 and 6 framed |
| 55 to 80 | Commune breakouts (7 rooms): meet, pick co-chairs, agree a meeting slot | Co-chair nominations, ballot 8 |
| 80 to 90 | Peace and Consensus nominations, name, close | Ballots 7 and 9 framed |

## The ballots

Voting opens straight after the session and runs 7 days. Founding decisions need two thirds of votes cast. Results go into `decisions/0001` onwards.

| # | Decision | Options | Recommended, and why |
|---|---|---|---|
| 1 | Adopt the Social Contract | Yes / No | **Yes.** Amendments can follow at any later Assembly. |
| 2 | Co-chair balance rule | (a) Strict: every pair includes at least one woman. (b) Balanced where the commune can. | **(a) Strict** is faithful to the model and to the reason the co-chair system exists. Ad tech's gender balance makes it harder in year one, which is the point. Choose (b) if a commune of 6 would otherwise go without co-chairs. |
| 3 | Licence | (a) AGPL seller, MIT client, CC BY-SA docs. (b) Apache-2.0 everywhere. (c) AGPL everywhere. | **(b).** It's what the repo starts with, it's the only option every member's employer is likely to allow, and it keeps (a) and (c) available later. See [LICENSING.md](LICENSING.md). |
| 4 | Developer share | 60% / 70% / 80% of gross on rendered paid ads | **70%.** Matches Brave and EthicalAds, and leaves 30% to run the network. |
| 5 | Ads for good | (a) 20% of impressions free for verified charities. (b) 20% of revenue donated. | **(a).** Option (b) leaves the network 10% of revenue, which cannot cover payouts, fraud controls and legal costs. |
| 6 | Legal home | (a) Fiscal host for costs now, and a UK Community Interest Company or co-operative before taking any advertiser money. (b) Form the entity now. (c) Stay informal and demo-only. | **(a).** Paying developers and charities needs an entity that can sign contracts, check identities and report tax. A CIC's asset lock suits ads for good; a co-op suits member ownership. Take legal advice before choosing. |
| 7 | Name | stdout Network / submitted alternatives | Decide by ranked choice. Check the GitHub organisation, domain and trademark search for each shortlisted name first; "stdout" is a crowded word. |
| 8 | Co-chairs | Nominees per commune, from the breakouts | Each commune confirms its pair; the Assembly ratifies all 14 seats together. |
| 9 | Peace and Consensus Committee | 3 to 5 from the nominees | Ranked choice. Nobody also standing for co-chair. |
| 10 | Fighting fund | (a) Adopt as drafted: 10% of profit, discretionary grants after 3 months' membership, private three-person panel, £10,000 ceiling. (b) Adopt with a different percentage or ceiling. (c) No fund. | **(a).** It costs nothing until there is profit, and it says what kind of group this is. |

Also confirm by simple majority: the Treasury spending limit for do-ocracy decisions (recommended £1,000 per item), the split of leftover profit between beer and marketing (recommended half each), the Committee's private reporting address, the fighting fund panel's private address, and when the door opens to developers and everyone else (recommended: the first quarterly Assembly).

## Within 14 days

- [ ] First Confederal Council meeting; convenors step down
- [ ] GitHub org created, one team per commune plus `council`, matching `.github/CODEOWNERS`
- [ ] Licence changed per ballot 3, if the Assembly chose (a) or (c)
- [ ] Every commune holds its first meeting and files notes in `communes/<name>/notes/`
- [ ] Treasury opens the fiscal host account and publishes a zero-balance first summary
- [ ] Market commune drafts rate card v1; Commons commune drafts advertising policy v1
- [ ] Decisions 0001 to 0010 merged
- [ ] Solidarity channel opened for job leads and introductions
- [ ] First gathering booked out of the beer pot, even if the pot is empty and everyone pays their own way
