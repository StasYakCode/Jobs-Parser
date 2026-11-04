from unittest import mock

from django.test import TestCase

from jobs.models import Company, Job, SearchQuery
from jobs.scraper import details, search
from jobs.scraper.http import NotFound, RateLimited
from jobs.scraper.parsers import parse_company, parse_job_detail, parse_search_page

SEARCH_HTML = """
<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:111">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/python-developer-at-acme-111?position=1"></a>
  <div class="base-search-card__info"><h3 class="base-search-card__title"> Python Developer </h3>
  <h4 class="base-search-card__subtitle"><a href="https://www.linkedin.com/company/acme-inc?trk=x">Acme Inc</a></h4>
  <span class="job-search-card__location">New York, NY</span>
  <time class="job-search-card__listdate" datetime="2026-10-30">3 days ago</time></div></div></li>
<li><div class="base-card job-search-card"><a class="base-card__full-link"
  href="https://www.linkedin.com/jobs/view/222?x=1"></a><h3 class="base-search-card__title">Backend</h3>
  <h4 class="base-search-card__subtitle">NoLink Corp</h4></div></li>
"""

DETAIL_HTML = """
<h2 class="top-card-layout__title">Python Developer</h2>
<a class="topcard__org-name-link" href="https://www.linkedin.com/company/acme-inc?trk=y">Acme Inc</a>
<span class="topcard__flavor topcard__flavor--bullet">New York, NY</span>
<span class="posted-time-ago__text">3 days ago</span>
<figcaption class="num-applicants__caption">Over 200 applicants</figcaption>
<code id="applyUrl"><!--"https://acme.com/apply?a=1&amp;b=2"--></code>
<div class="show-more-less-html__markup"><p>Build <b>APIs</b></p></div>
<ul><li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Seniority level</h3>
<span class="description__job-criteria-text">Mid-Senior level</span></li>
<li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Employment type</h3>
<span class="description__job-criteria-text">Full-time</span></li></ul>
"""

COMPANY_HTML = """
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme Inc",
"description":"We build things","sameAs":"https://acme.com","address":{"streetAddress":"1 Main St",
"addressLocality":"New York","addressCountry":"US"},"numberOfEmployees":{"value":1200}}</script>
<div data-test-id="about-us__industry"><dd>Software Development</dd></div>
<div data-test-id="about-us__size"><dd>1,001-5,000 employees</dd></div>
<div>54,321 followers</div>
"""


class ParserTests(TestCase):
    def test_search_page(self):
        cards = parse_search_page(SEARCH_HTML)
        self.assertEqual([c["job_id"] for c in cards], ["111", "222"])
        self.assertEqual(cards[0]["company_slug"], "acme-inc")
        self.assertEqual(cards[0]["title"], "Python Developer")
        self.assertEqual(str(cards[0]["listed_at"]), "2026-10-30")
        self.assertEqual(cards[1]["company_slug"], "")

    def test_job_detail(self):
        d = parse_job_detail(DETAIL_HTML)
        self.assertEqual(d["seniority_level"], "Mid-Senior level")
        self.assertEqual(d["employment_type"], "Full-time")
        self.assertEqual(d["applicants_count"], 200)
        self.assertEqual(d["apply_url"], "https://acme.com/apply?a=1&b=2")
        self.assertEqual(d["company_slug"], "acme-inc")
        self.assertIn("APIs", d["description_text"])

    def test_company(self):
        c = parse_company(COMPANY_HTML)
        self.assertEqual(c["name"], "Acme Inc")
        self.assertEqual(c["employees_count"], 1200)
        self.assertEqual(c["industry"], "Software Development")
        self.assertEqual(c["followers"], 54321)
        self.assertIn("New York", c["address"])


class SearchTests(TestCase):
    def setUp(self):
        self.q = SearchQuery.objects.create(keywords="Python Developer", country="USA")

    def test_no_duplicates_on_resave(self):
        cards = parse_search_page(SEARCH_HTML)
        self.assertEqual(search.save_cards(self.q, cards), 2)
        self.assertEqual(search.save_cards(self.q, cards), 0)
        self.assertEqual(Job.objects.count(), 2)
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(self.q.jobs.count(), 2)

    def test_same_job_in_two_queries(self):
        q2 = SearchQuery.objects.create(keywords="Python Developer", country="Canada")
        cards = parse_search_page(SEARCH_HTML)
        search.save_cards(self.q, cards)
        search.save_cards(q2, cards)
        self.assertEqual(Job.objects.count(), 2)
        self.assertEqual(Job.objects.get(job_id="111").queries.count(), 2)

    def test_pagination_and_resume(self):
        page = SEARCH_HTML
        client = mock.Mock()
        client.get.side_effect = [page, RateLimited("429")]
        ok = search.run_search(self.q, client)
        self.assertFalse(ok)
        self.q.refresh_from_db()
        self.assertEqual(self.q.status, SearchQuery.Status.FAILED)
        self.assertEqual(self.q.progress["current"]["start"], 2)
        # повторный запуск продолжает со start=2 и завершается на пустой странице
        client.get.side_effect = ["<ul></ul>"]
        self.assertTrue(search.run_search(self.q, client))
        self.assertEqual(client.get.call_args.kwargs["params"]["start"], 2)
        self.assertEqual(self.q.jobs.count(), 2)

    def test_slice_plan_only_when_saturated(self):
        self.assertEqual(len(list(search.slice_plan({"done": {"base": 120}}))), 1)
        self.assertGreater(len(list(search.slice_plan({"done": {"base": 950}}))), 20)


class DetailsTests(TestCase):
    def setUp(self):
        q = SearchQuery.objects.create(keywords="x", country="y")
        search.save_cards(q, parse_search_page(SEARCH_HTML))

    def test_handle_job_done_and_company(self):
        client = mock.Mock()
        client.get.side_effect = [DETAIL_HTML, COMPANY_HTML]
        job = details.claim_jobs(1)[0]
        details.handle_job(job, client)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DONE)
        self.assertEqual(job.employment_type, "Full-time")
        self.assertEqual(job.company.status, Company.Status.DONE)
        self.assertEqual(job.company.industry, "Software Development")

    def test_not_found_and_failure_and_rate_limit(self):
        client = mock.Mock()
        j1, j2 = details.claim_jobs(2)
        client.get.side_effect = NotFound("x")
        details.handle_job(j1, client)
        self.assertEqual(Job.objects.get(pk=j1.pk).status, Job.Status.NOT_FOUND)
        client.get.side_effect = ValueError("boom")
        details.handle_job(j2, client)
        j2.refresh_from_db()
        self.assertEqual((j2.status, j2.attempts), (Job.Status.FAILED, 1))
        client.get.side_effect = RateLimited("429")
        with self.assertRaises(RateLimited):
            details.handle_job(j2, client)
        self.assertEqual(Job.objects.get(pk=j2.pk).status, Job.Status.NEW)

    def test_claim_is_exclusive(self):
        first = details.claim_jobs(10)
        self.assertEqual(len(first), 2)
        self.assertEqual(details.claim_jobs(10), [])
