"""Per-source caveats shown on every major page and on the Sources page."""

CAVEATS = {
    "scorecard": {
        "name": "College Scorecard (U.S. Dept. of Education)",
        "kind": "Administrative tax data (IRS)",
        "points": [
            "Earnings cover only graduates who received federal financial aid (Pell grants or federal loans). "
            "Students who paid without federal aid are not counted, so results can differ from the full class.",
            "Medians are for graduates who were working and not enrolled in further schooling in the measurement year.",
            "Cells with too few graduates are privacy-suppressed (shown as “suppressed”), which is common for small majors.",
            "National medians (EARN_MDN_*_NAT) pool every institution's bachelor's graduates in the same 4-digit CIP code.",
            "Programs are grouped at the 4-digit CIP level, so one CIP can combine several Rutgers majors.",
        ],
    },
    "pseo": {
        "name": "Post-Secondary Employment Outcomes (U.S. Census Bureau)",
        "kind": "Administrative wage records (state UI records via LEHD)",
        "points": [
            "Covers all graduates reported by New Jersey's partner institutions, regardless of financial aid, "
            "but only those found in covered employment with earnings above a minimum threshold.",
            "Self-employed people, most federal workers, and people working abroad are missing.",
            "Earnings are pooled over several graduation cohorts and adjusted for inflation by the Census Bureau.",
            "Industry and region destinations are published only at the 2-digit CIP level (e.g. all Engineering), not by individual major.",
            "Values that do not meet Census disclosure standards are suppressed. Ten-year earnings exist only for older cohorts.",
            "New Jersey institutions joined PSEO in the August 2026 release; NJ statewide numbers combine every NJ partner school.",
        ],
    },
    "fds": {
        "name": "Rutgers First-Destination Survey (Career Exploration and Success)",
        "kind": "Self-reported survey",
        "points": [
            "Salaries and employers are mostly self-reported by graduates within about six months of graduation "
            "(NACE standards also let schools add outcomes verified from other sources).",
            "The knowledge rate is the share of graduates with a known outcome. A lower knowledge rate means more risk "
            "that respondents differ from non-respondents.",
            "Median salaries for small groups (low n) are unstable.",
            "Most figures here are school-level (e.g. all of SAS), not major-level, because the public site only shows "
            "per-major pages one at a time. The live site was down when this data was collected, so the numbers come "
            "from Internet Archive snapshots; class year is shown with every figure.",
        ],
    },
    "nyfed": {
        "name": "New York Fed: The Labor Market for Recent College Graduates",
        "kind": "Survey data (American Community Survey via IPUMS)",
        "points": [
            "National, not Rutgers-specific. Recent graduates are ages 22–27 with a bachelor's degree; mid-career is ages 35–45.",
            "Underemployment means working in a job that typically does not require a college degree.",
            "NY Fed majors are broader ACS categories, matched to CIP codes with a hand-built crosswalk (data/crosswalks/nyfed_major_cip.csv).",
        ],
    },
    "bls": {
        "name": "BLS Employment Projections + NCES CIP-to-SOC crosswalk",
        "kind": "Projections and wage estimates",
        "points": [
            "Job growth is BLS's 10-year projection for occupations linked to the major by the official CIP-to-SOC crosswalk; "
            "it is not a forecast for any single graduate.",
            "Where possible, only occupations that typically require a bachelor's degree or higher are used.",
            "Median wages are for all workers in the occupation (all ages, all experience levels), not new graduates.",
        ],
    },
    "nace": {
        "name": "NACE Winter 2026 Salary Survey (published summary)",
        "kind": "Employer survey",
        "points": [
            "Projected average base starting salaries for the Class of 2026, reported by NACE member employers (150 responses).",
            "Only broad categories are public; the detailed by-major table is members-only, so it is not used here.",
            "Averages are pulled up by high salaries and are not comparable to the medians from other sources.",
        ],
    },
    "not_used": {
        "name": "Sources considered but not used",
        "kind": "",
        "points": [
            "ACS/IPUMS microdata needs a registered IPUMS account; the NY Fed tables above are built from the same ACS data.",
            "LinkedIn was not scraped (against its terms of service).",
            "Rutgers–Camden and Rutgers–Newark were left out by request.",
        ],
    },
}
