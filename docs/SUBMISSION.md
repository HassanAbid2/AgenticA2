# GigBid submission package

- [Public repository](https://github.com/HassanAbid2/AgenticA2)
- [Live GigBid application](https://gigbid-uxin.onrender.com)
- [R&D report PDF](report/GigBid_RD_Report.pdf) (attach this file in Classroom)
- [Public demo video download](https://raw.githubusercontent.com/HassanAbid2/AgenticA2/bc9a801233910b8876eaec52cd683a96b682d446/docs/video/gigbid-demo.webm) and [local WebM](video/gigbid-demo.webm)
- [Playwright end-to-end test report](test-reports/playwright.html) (download and open locally)
- [Technical write-up](WRITEUP.md)
- [Portfolio MCP installation and configuration](../mcp_servers/portfolio/README.md)
- [Measured results and remaining evaluation gaps](RESULTS.md)

The checked-in Playwright report covers five passing browser tests. The separate demo recording
runs for 3:01 and shows an approved proposal, a skipped scam, a blocked instruction and an approved client reply.

The brief asks for one Google Classroom submission, a PDF attachment, and public links. The exact
repository paths are in the brief's Required Directory Structure. It gives no folder, ZIP,
roll-number or PDF filename pattern. Use the WebM download link in Classroom or upload the same
recording to a video host for streaming.

| Required item | Audit status |
|---|---|
| Repository and required paths | Public GitHub repository. The local source export uses the `gigbid/` root. |
| PDF report and demo | Report attached separately. The repository also contains the Playwright report, 30-second GIF, both graphs and MCP Inspector screenshots. |
| Installable Portfolio MCP | The public Git install via `uvx` initialized over stdio and returned portfolio evidence. |
| Technical write-up | The public repository copy meets the brief's length requirement. The required LinkedIn, Medium, or personal blog URL is still outstanding. |
| Public app and reviewer login | The [Render home page](https://gigbid-uxin.onrender.com) and [health endpoint](https://gigbid-uxin.onrender.com/health) respond. Check the reviewer login and open a proposal before submitting. Share credentials in a private Classroom comment. |
| Public trace links | Pending for the skipped scam, approved proposal, Critic loop and crash-and-resume examples. |
| Evaluation evidence | Partial. The tool study lacks the remaining 19 tasks for GigBid's tool design. The hosted model comparison, shipped proposal metrics, injection before/after study and 50-job orchestration comparison remain incomplete. A single-agent grounded-draft example is also unverified. |
| Human evaluation | Pending. The student must supply their own 30 judge labels and classmates must provide a blind pairwise panel. The assistant-labelled CPU pilot is included separately. |
| Instructor hidden test | Results unavailable. The brief assigns this run to the instructor after the deadline. |

The fixed offline GigSim run submitted five of six sampled jobs, with one simulated reply and no
simulated hires. Its output is in [gigsim_outcomes.json](../evals/results/gigsim_outcomes.json).
The supplied starter ZIP contains a skeleton and sample data. This repository uses its documented
[synthetic GigSim and corpus](DATA_CARD.md).

The supplied brief lists **12 November 2026 at 11:59 PM PKT** and says later commits are ignored.
The current repository has no commit dated on or before that cutoff. Confirm any extension in Classroom.
