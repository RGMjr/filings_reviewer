--
-- PostgreSQL database dump
--

\restrict OJ6rk2Uv9hb8o96zIkdnLPzDQ9FLFE4KTuAMfQdGy9KzcKe2jmzQMwxDtoXeIQz

-- Dumped from database version 15.16 (08ce83f)
-- Dumped by pg_dump version 15.16 (Debian 15.16-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: review_decisions; Type: TABLE DATA; Schema: public; Owner: neondb_owner
--

INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (1, 47, 'reject', NULL, 'correct value is 30%', 'wrong_value', NULL, NULL, 228, '2026-03-17 13:15:32.175844+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (2, 48, 'accept', 'cm_revenue_concentration', NULL, NULL, NULL, NULL, 12, '2026-03-17 13:15:48.03998+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (3, 49, 'accept', 'cm_revenue_concentration', NULL, NULL, NULL, NULL, 3, '2026-03-17 13:15:55.686027+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (4, 1, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 6, '2026-03-17 13:16:41.94218+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (5, 43, 'reject', NULL, NULL, 'wrong_value', NULL, NULL, 45, '2026-03-17 13:17:33.582857+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (6, 2, 'reject', NULL, 'correct value is 88000', 'wrong_value', NULL, NULL, 32, '2026-03-17 13:18:12.227806+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (7, 46, 'reject', NULL, 'context shows this is not revenue concentration but statement that no customer comprised more than 10%', 'not_a_metric', NULL, NULL, 51, '2026-03-17 13:19:09.828168+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (8, 44, 'reject', NULL, NULL, 'wrong_value', NULL, NULL, 37, '2026-03-17 13:19:53.383283+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (9, 11, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 16, '2026-03-17 13:20:15.671948+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (10, 14, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 8, '2026-03-17 13:20:29.983132+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (11, 3, 'reject', NULL, NULL, 'wrong_value', NULL, NULL, 57, '2026-03-17 13:21:33.760652+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (12, 15, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 9, '2026-03-17 13:21:49.655866+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (13, 22, 'reject', NULL, 'this is a definition of how they calculate NRR', 'other', NULL, NULL, 280, '2026-03-17 13:26:36.128908+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (14, 13, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 4, '2026-03-17 13:26:46.855462+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (15, 7, 'accept', 'cm_daily_active_users', NULL, NULL, NULL, NULL, 4, '2026-03-17 13:26:56.807533+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (16, 9, 'reject', NULL, 'correct value is 138%', 'wrong_value', NULL, NULL, 29, '2026-03-17 13:27:31.997333+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (17, 16, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 20, '2026-03-17 13:27:58.56369+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (18, 21, 'reject', NULL, NULL, 'not_a_metric', NULL, NULL, 25, '2026-03-17 13:28:29.682986+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (19, 17, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 7, '2026-03-17 13:28:43.132851+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (20, 42, 'reject', NULL, NULL, 'not_a_metric', NULL, NULL, 11, '2026-03-17 13:29:00.733611+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (21, 45, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 16, '2026-03-17 13:29:22.951464+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (22, 10, 'reject', NULL, NULL, 'wrong_value', NULL, NULL, 22, '2026-03-17 13:29:52.359163+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (23, 18, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 8, '2026-03-17 13:30:06.622778+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (24, 25, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 4, '2026-03-17 13:30:16.519413+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (25, 19, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 17, '2026-03-17 13:30:39.932022+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (26, 26, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 60, '2026-03-17 13:31:46.505443+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (27, 27, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 30, '2026-03-17 13:32:22.815566+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (28, 8, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 9, '2026-03-17 13:32:39.639432+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (29, 20, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 8, '2026-03-17 13:32:53.746001+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (30, 28, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 70, '2026-03-17 13:34:09.539908+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (31, 29, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 4, '2026-03-17 13:34:21.180957+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (32, 30, 'accept', 'cm_customers_period_end', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:34:30.744741+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (33, 6, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 3, '2026-03-17 13:34:41.250443+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (34, 4, 'reject', NULL, NULL, 'wrong_value', NULL, NULL, 10, '2026-03-17 13:34:57.838376+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (35, 31, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 8, '2026-03-17 13:35:12.413716+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (36, 32, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:35:20.567807+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (37, 33, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:35:28.82749+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (38, 34, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:35:36.614811+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (39, 35, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 1, '2026-03-17 13:35:44.36505+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (40, 36, 'accept', 'cm_large_customers_period_end', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:35:51.979056+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (41, 12, 'reject', NULL, 'this comes from the wrong row', 'wrong_value', NULL, NULL, 27, '2026-03-17 13:36:25.225645+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (42, 37, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 3, '2026-03-17 13:36:34.110825+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (43, 38, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 0, '2026-03-17 13:36:40.810406+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (44, 39, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 1, '2026-03-17 13:36:47.611523+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (45, 40, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 3, '2026-03-17 13:36:56.927631+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (46, 41, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 2, '2026-03-17 13:37:05.23326+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (47, 5, 'reject', NULL, NULL, 'not_a_metric', NULL, NULL, 23, '2026-03-17 13:37:34.141298+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (48, 23, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 4, '2026-03-17 13:37:44.221256+00');
INSERT INTO public.review_decisions (decision_id, candidate_id, decision, assigned_metric_id, rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds, created_at) VALUES (49, 24, 'accept', 'cm_net_revenue_retention', NULL, NULL, NULL, NULL, 3, '2026-03-17 13:37:53.349289+00');


--
-- Name: review_decisions_decision_id_seq; Type: SEQUENCE SET; Schema: public; Owner: neondb_owner
--

SELECT pg_catalog.setval('public.review_decisions_decision_id_seq', 49, true);


--
-- PostgreSQL database dump complete
--

\unrestrict OJ6rk2Uv9hb8o96zIkdnLPzDQ9FLFE4KTuAMfQdGy9KzcKe2jmzQMwxDtoXeIQz

