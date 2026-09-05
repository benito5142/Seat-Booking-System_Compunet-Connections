"""
CONCURRENT SEAT RESERVATION SAFETY TEST SUITE
=============================================

This module verifies the most critical requirement of the Seat Booking System:
    "A seat can never be successfully reserved by two users simultaneously."

THE RACE CONDITION BEING TESTED (CHECK-THEN-ACT):
-------------------------------------------------
In an unsafe web reservation implementation, two requests (Request A and Request B)
arriving at the server simultaneously for the same seat (e.g., 'A1') encounter a classic
Time-of-Check to Time-of-Wait / Time-of-Act (TOCTOU) race condition:

    Thread A: SELECT status FROM seats WHERE id = 'A1';  --> returns 'AVAILABLE'
    Thread B: SELECT status FROM seats WHERE id = 'A1';  --> returns 'AVAILABLE'
    Thread A: (Application logic: "A1 is available, proceeding to create hold")
    Thread B: (Application logic: "A1 is available, proceeding to create hold")
    Thread A: INSERT INTO holds ...; UPDATE seats SET status = 'HELD' WHERE id = 'A1';
    Thread B: INSERT INTO holds ...; UPDATE seats SET status = 'HELD' WHERE id = 'A1';
    Thread A: COMMIT --> HTTP 201 Created (Hold Token A)
    Thread B: COMMIT --> HTTP 201 Created (Hold Token B)

Result: Both users believe they successfully reserved seat A1. Two active hold tokens exist
for the exact same seat. When users go to purchase or arrive at the venue, double-booking occurs.

WHY SEQUENTIAL TESTS ARE INSUFFICIENT:
-------------------------------------
A test that executes:
    response_a = client.post('/holds', json={'seats': ['A1']})
    response_b = client.post('/holds', json={'seats': ['A1']})
is purely sequential. By the time Request B executes, Request A's transaction has completely
finished, updated the database, and committed. That merely tests that an already-held seat
cannot be re-held. It does NOT test what happens when two transactions run interleaved or
simultaneously, and does NOT prove concurrency safety.

HOW TRANSACTIONS, ROW-LEVEL LOCKS, AND ATOMIC TRANSITIONS PREVENT THIS:
---------------------------------------------------------------------
1. DETERMINISTIC ROW-LEVEL LOCKING:
   All requested seat IDs are sorted in strict ascending order (e.g., A1 < A2 < A3)
   before any database query is issued. The transaction issues a locking query:
       SELECT * FROM seats WHERE id IN (:seat_ids) ORDER BY id ASC FOR UPDATE;
   In MySQL/InnoDB, this places an exclusive index record lock (X-lock) on each requested seat.
   Any concurrent transaction attempting to lock or modify the same seat rows is blocked
   until the holding transaction commits or rolls back.

2. ATOMIC CONDITIONAL STATE TRANSITION:
   To eliminate any vulnerability across transaction isolation levels or database dialects,
   the status transition is performed via an atomic conditional UPDATE:
       UPDATE seats 
       SET status = 'HELD', version = version + 1, updated_at = :now
       WHERE id IN (:sorted_ids) AND status = 'AVAILABLE';
   If the number of affected rows does not strictly equal the number of requested seats,
   the transaction detects that another transaction acquired one or more seats first.
   The entire transaction is immediately rolled back, and an HTTP 409 Conflict is returned.

3. SCHEMA-LEVEL CONSTRAINTS AS DEFENSE-IN-DEPTH:
   - `uq_bookings_hold_id` (UNIQUE on hold_id in `bookings`):
     Prevents the same hold from being confirmed into multiple bookings.
   - `uq_booking_seats_seat_id` (UNIQUE on seat_id in `booking_seats`):
     Guarantees at the storage engine level that no seat can be booked more than once for the event.
   - `uq_hold_seats_hold_seat` (UNIQUE on hold_id, seat_id in `hold_seats`):
     Prevents duplicate seat associations within a hold.

4. WHY EXACTLY ONE REQUEST WINS:
   When two requests arrive concurrently:
   - Whichever transaction obtains the row lock / atomic update first updates the seat from
     AVAILABLE to HELD.
   - The second transaction either:
     a) Blocks on row lock and upon unblocking reads status='HELD', failing verification; OR
     b) Attempts the atomic update with WHERE status = 'AVAILABLE', matching 0 rows, and rolls back.
   - Therefore, exactly ONE request receives HTTP 201 Created and a valid hold token.
   - Exactly ONE request receives HTTP 409 Conflict with details of the unavailable seat.
   - The database contains exactly ONE active hold and ONE hold_seat entry for that seat.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import get_db
from tests.conftest import test_engine, TestingSessionLocal


class TestConcurrentSeatReservationSafety:
    """
    Test suite exercising genuine concurrency against the real FastAPI endpoints
    and relational database transaction/locking behaviors.
    """

    @pytest.fixture(autouse=True)
    def clean_slate(self, reset_test_db):
        """Ensure clean database state before each concurrency test."""
        pass

    def test_concurrent_holds_identical_seat(self, client: TestClient):
        """
        REQUIREMENTS 1 & 2: GENUINE CONCURRENCY TEST & ASSERTION
        
        Two independent requests attempt to hold the EXACT SAME SEAT ('A1')
        at approximately the same time.
        
        Execution:
        - Two threads execute POST /holds for seat ['A1'] concurrently.
        - A threading.Barrier(2) synchronizes the exact release instant so both
          threads enter the FastAPI request pipeline and database transaction concurrently.
        
        Assertions:
        - Exactly one request succeeds (HTTP 201 Created).
        - Exactly one request fails (HTTP 409 Conflict).
        - The successful request receives a valid hold payload (token, seat A1, 300s TTL).
        - The failed request receives an error response detailing the unavailable seat.
        - The database contains exactly ONE active hold for seat A1.
        - The database contains NO duplicate holds or partial reservations.
        """
        barrier = threading.Barrier(2)
        results = []

        def submit_hold_request(user_identifier: str):
            # Wait at barrier so both threads fire POST /holds at the exact same instant
            barrier.wait()
            resp = client.post(
                "/holds",
                json={"seats": ["A1"], "user_id": user_identifier},
            )
            return {
                "user_id": user_identifier,
                "status_code": resp.status_code,
                "data": resp.json(),
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(submit_hold_request, "user_concurrent_A")
            future_b = executor.submit(submit_hold_request, "user_concurrent_B")
            results = [future_a.result(), future_b.result()]

        status_codes = [r["status_code"] for r in results]
        
        # 1. Exactly one request must succeed with 201 Created
        success_results = [r for r in results if r["status_code"] == 201]
        assert len(success_results) == 1, (
            f"Expected exactly 1 successful request (201), got {len(success_results)}. "
            f"Statuses: {status_codes}"
        )

        # 2. Exactly one request must fail with 409 Conflict
        conflict_results = [r for r in results if r["status_code"] == 409]
        assert len(conflict_results) == 1, (
            f"Expected exactly 1 conflict request (409), got {len(conflict_results)}. "
            f"Statuses: {status_codes}"
        )

        # 3. Successful request receives valid hold details
        winner = success_results[0]["data"]
        assert "hold_token" in winner
        assert winner["seats"] == ["A1"]
        assert winner["status"] == "held"
        assert winner["expires_in_seconds"] == 300
        assert "expires_at" in winner

        # 4. Failed request receives appropriate conflict response
        loser = conflict_results[0]["data"]
        assert "detail" in loser
        error_detail = loser["detail"]
        if isinstance(error_detail, dict):
            assert "A1" in str(error_detail.get("unavailable_seats", [])) or "A1" in error_detail.get("message", "")
        else:
            assert "A1" in str(error_detail) or "unavailable" in str(error_detail).lower()

        # 5. Database State Verification
        with test_engine.connect() as conn:
            # Check holds table: exactly 1 active hold exists
            active_holds = conn.exec_driver_sql(
                "SELECT id, hold_token, status FROM holds WHERE status = 'ACTIVE'"
            ).fetchall()
            assert len(active_holds) == 1, f"Expected 1 active hold in DB, found {len(active_holds)}"
            assert active_holds[0][1] == winner["hold_token"]

            # Check hold_seats table: exactly 1 entry for seat A1
            hold_seats = conn.exec_driver_sql(
                "SELECT hold_id, seat_id FROM hold_seats WHERE seat_id = 'A1'"
            ).fetchall()
            assert len(hold_seats) == 1, f"Expected 1 hold_seat record for A1, found {len(hold_seats)}"
            assert hold_seats[0][0] == active_holds[0][0]

            # Check seats table: seat A1 is HELD with version incremented
            seat_record = conn.exec_driver_sql(
                "SELECT id, status, version FROM seats WHERE id = 'A1'"
            ).fetchone()
            assert seat_record[1] == "HELD"
            assert seat_record[2] >= 1

    def test_concurrent_overlapping_seats_all_or_nothing(self, client: TestClient):
        """
        REQUIREMENT 5 & 6: MULTI-SEAT ATOMICITY & OVERLAPPING REQUESTS
        
        Consider the overlapping concurrent scenario:
            Request A -> ['A1', 'A2']
            Request B -> ['A2', 'A3']
        
        Because 'A2' is contested:
        - Exactly one request must win both of its requested seats.
        - The other request must fail completely (HTTP 409 Conflict).
        - ALL-OR-NOTHING INVARIANT: No partial holds!
          If Request A wins: A1 and A2 are held; A3 MUST REMAIN AVAILABLE.
          If Request B wins: A2 and A3 are held; A1 MUST REMAIN AVAILABLE.
        """
        barrier = threading.Barrier(2)

        def worker_a():
            barrier.wait()
            return client.post("/holds", json={"seats": ["A1", "A2"], "user_id": "user_multi_A"})

        def worker_b():
            barrier.wait()
            return client.post("/holds", json={"seats": ["A2", "A3"], "user_id": "user_multi_B"})

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(worker_a)
            fut_b = executor.submit(worker_b)
            resp_a = fut_a.result()
            resp_b = fut_b.result()

        statuses = [resp_a.status_code, resp_b.status_code]
        assert 201 in statuses, f"Expected one 201 Created, got statuses: {statuses}"
        assert 409 in statuses, f"Expected one 409 Conflict, got statuses: {statuses}"

        if resp_a.status_code == 201:
            winning_req = "A"
            assert resp_a.json()["seats"] == ["A1", "A2"]
            assert resp_b.status_code == 409
        else:
            winning_req = "B"
            assert resp_b.json()["seats"] == ["A2", "A3"]
            assert resp_a.status_code == 409

        # Database atomicity verification:
        with test_engine.connect() as conn:
            seat_rows = conn.exec_driver_sql(
                "SELECT id, status FROM seats WHERE id IN ('A1', 'A2', 'A3') ORDER BY id ASC"
            ).fetchall()
            status_map = {row[0]: row[1] for row in seat_rows}

            if winning_req == "A":
                # Request A won A1 and A2 -> A3 MUST be AVAILABLE!
                assert status_map["A1"] == "HELD"
                assert status_map["A2"] == "HELD"
                assert status_map["A3"] == "AVAILABLE", (
                    "CRITICAL VIOLATION: A3 was left partially held when Request B failed!"
                )
            else:
                # Request B won A2 and A3 -> A1 MUST be AVAILABLE!
                assert status_map["A1"] == "AVAILABLE", (
                    "CRITICAL VIOLATION: A1 was left partially held when Request A failed!"
                )
                assert status_map["A2"] == "HELD"
                assert status_map["A3"] == "HELD"

            # Total held seats across DB must be exactly 2
            total_held = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM seats WHERE status = 'HELD'"
            ).scalar()
            assert total_held == 2, f"Expected exactly 2 held seats, found {total_held}"

    def test_deadlock_prevention_with_reverse_seat_ordering(self, client: TestClient):
        """
        REQUIREMENT 7: DEADLOCK PREVENTION VIA DETERMINISTIC LOCKING ORDER
        
        Two requests request overlapping sets of seats, but specified in DIFFERENT/REVERSED orders:
            Request A: ['B2', 'B1'] -> (reverse order)
            Request B: ['B1', 'B2'] -> (forward order)
        
        Because our implementation deterministically sorts all seat requests in ascending
        alphabetical order (B1 then B2) before acquiring database locks or row updates,
        neither transaction can wait on a lock held by the other in an inverse cycle.
        
        Result: No unhandled deadlock occurs; one request succeeds and the other receives 409.
        """
        barrier = threading.Barrier(2)

        def worker_rev():
            barrier.wait()
            return client.post("/holds", json={"seats": ["B2", "B1"], "user_id": "rev_user"})

        def worker_fwd():
            barrier.wait()
            return client.post("/holds", json={"seats": ["B1", "B2"], "user_id": "fwd_user"})

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_rev = executor.submit(worker_rev)
            fut_fwd = executor.submit(worker_fwd)
            resp_rev = fut_rev.result()
            resp_fwd = fut_fwd.result()

        statuses = sorted([resp_rev.status_code, resp_fwd.status_code])
        assert statuses == [201, 409], f"Expected [201, 409], got {statuses}"

        # DB verification
        with test_engine.connect() as conn:
            held_count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM seats WHERE id IN ('B1', 'B2') AND status = 'HELD'"
            ).scalar()
            assert held_count == 2
            active_holds_count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM holds WHERE status = 'ACTIVE'"
            ).scalar()
            assert active_holds_count == 1

    def test_concurrent_booking_confirmations_for_same_hold(self, client: TestClient):
        """
        REQUIREMENT 8: BOOKING CONFIRMATION CONCURRENCY SAFETY
        
        A hold can result in ONLY ONE confirmed booking.
        If two simultaneous confirmation requests are made for the same hold:
            Request A: POST /holds/{hold_token}/confirm
            Request B: POST /holds/{hold_token}/confirm
        
        Both requests execute concurrently.
        
        Assertions:
        - Exactly ONE request receives HTTP 201 Created with a confirmed booking reference.
        - Exactly ONE request receives HTTP 400 Bad Request indicating the hold was already confirmed.
        - Exactly ONE record exists in the bookings table for this hold (enforced also by UNIQUE uq_bookings_hold_id).
        - Associated seats are in status 'BOOKED', not duplicated.
        """
        # 1. Create initial hold
        create_resp = client.post("/holds", json={"seats": ["C1", "C2"], "user_id": "buyer"})
        assert create_resp.status_code == 201
        hold_token = create_resp.json()["hold_token"]

        barrier = threading.Barrier(2)

        def confirm_worker(worker_id: str):
            barrier.wait()
            return client.post(
                f"/holds/{hold_token}/confirm",
                json={"user_id": f"confirm_{worker_id}"},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(confirm_worker, "1")
            fut2 = executor.submit(confirm_worker, "2")
            res1 = fut1.result()
            res2 = fut2.result()

        status_codes = sorted([res1.status_code, res2.status_code])
        assert status_codes == [201, 400], (
            f"Expected one 201 Created and one 400 Bad Request, got {status_codes}"
        )

        success_res = res1 if res1.status_code == 201 else res2
        error_res = res2 if res1.status_code == 201 else res1

        # Verify successful confirmation response
        booking_data = success_res.json()
        assert "booking_reference" in booking_data
        assert booking_data["status"] == "confirmed"
        assert set(booking_data["seats"]) == {"C1", "C2"}

        # Verify error response for the second confirmation
        assert "already been confirmed" in str(error_res.json()).lower()

        # Verify Database state
        with test_engine.connect() as conn:
            # Only 1 booking in database
            bookings = conn.exec_driver_sql(
                "SELECT id, booking_reference, hold_id, status FROM bookings WHERE hold_id = (SELECT id FROM holds WHERE hold_token = ?)",
                (hold_token,),
            ).fetchall()
            assert len(bookings) == 1, f"Expected exactly 1 booking in DB, found {len(bookings)}"
            assert bookings[0][1] == booking_data["booking_reference"]

            # Booking seats has exactly 2 records
            b_seats = conn.exec_driver_sql(
                "SELECT seat_id FROM booking_seats WHERE booking_id = ?",
                (bookings[0][0],),
            ).fetchall()
            assert {row[0] for row in b_seats} == {"C1", "C2"}

            # Seats are now BOOKED
            seat_statuses = conn.exec_driver_sql(
                "SELECT id, status FROM seats WHERE id IN ('C1', 'C2')"
            ).fetchall()
            for row in seat_statuses:
                assert row[1] == "BOOKED"
