import math
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> UserProfile | None:
        return await self.session.get(UserProfile, user_id)

    async def create(
        self,
        user_id: int,
        initial_vector: list[float],
        *,
        interest_tags: list[str] | None = None,
        mbti_scores: list[float] | None = None,
    ) -> UserProfile:
        profile = UserProfile(
            user_id=user_id,
            personality_vector=initial_vector,
            interest_tags=interest_tags or [],
            mbti_scores=mbti_scores,
            msg_count=0,
            updated_at=datetime.utcnow(),
        )
        self.session.add(profile)
        return profile

    async def update_vector(self, user_id: int, new_vector: list[float], msg_count: int) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        profile.personality_vector = new_vector
        profile.msg_count = msg_count
        profile.updated_at = datetime.utcnow()

    async def update_mbti(self, user_id: int, mbti_scores: list[float]) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        profile.mbti_scores = mbti_scores
        profile.updated_at = datetime.utcnow()

    async def add_tags(self, user_id: int, tags: list[str]) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        # Reassign a new list so SQLAlchemy detects the ARRAY change.
        merged = list(profile.interest_tags or [])
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
        profile.interest_tags = merged

    async def update_location(self, user_id: int, lat: float, lon: float) -> None:
        profile = await self.get(user_id)
        if profile is None:
            return
        profile.latitude = lat
        profile.longitude = lon

    async def find_best_matches(
        self,
        query_vector: list[float],
        candidate_ids: list[int],
        lat: float | None,
        lon: float | None,
        radius_km: float,
        top_k: int,
        neutral_geo_weight: float = 0.5,
        compat_matrix: list[float] | None = None,
    ) -> list[int]:
        """Возвращает до top_k user_id из candidate_ids, отсортированных по
        combined_score = similarity * geo_weight (убывание).

        similarity = cosine, либо bilinear `v_a^T·M·v_b` если передана compat_matrix
        (Фаза 6). pgvector <=> остаётся быстрым ANN-pre-filter в любом случае.
        """
        if not candidate_ids:
            return []

        # pgvector оператор <=> возвращает косинусное РАССТОЯНИЕ [0, 2];
        # cosine_similarity = 1 - distance. Литерал безопасен — это наши float'ы.
        vec_literal = f"'[{','.join(str(v) for v in query_vector)}]'::vector"

        # personality_vector::text — чтобы парсить детерминированно (на raw text()-запросе
        # pgvector-кодек не гарантирован, значение может прийти строкой).
        stmt = text(f"""
            SELECT
                user_id,
                latitude,
                longitude,
                personality_vector::text AS pvec,
                1 - (personality_vector <=> {vec_literal}) AS cosine_sim
            FROM user_profiles
            WHERE user_id = ANY(:ids)
            ORDER BY personality_vector <=> {vec_literal}
            LIMIT :limit
        """)

        rows = (
            await self.session.execute(
                stmt,
                {"ids": candidate_ids, "limit": min(top_k * 5, len(candidate_ids))},
            )
        ).fetchall()

        def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            R = 6371.0
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlam = math.radians(lon2 - lon1)
            a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        def geo_weight(rlat: float | None, rlon: float | None) -> float:
            # Нет координат у любого из двоих → нейтральный вес (не лучший и не худший):
            # эквивалент «средней дистанции» ≈ radius_km * ln(1/neutral) км.
            if lat is None or lon is None or rlat is None or rlon is None:
                return neutral_geo_weight
            return math.exp(-haversine(lat, lon, rlat, rlon) / radius_km)

        def parse_vec(raw) -> list[float]:
            if isinstance(raw, (list, tuple)):
                return [float(x) for x in raw]
            return [float(x) for x in str(raw).strip("[]").split(",") if x.strip()]

        def bilinear(va: list[float], M: list[float], vb: list[float]) -> float:
            """v_a^T · M · v_b (M построчно, 144 элемента для 12×12)."""
            n = 12
            norm_a = math.sqrt(sum(x * x for x in va)) or 1.0
            norm_b = math.sqrt(sum(x * x for x in vb)) or 1.0
            an = [x / norm_a for x in va]
            bn = [x / norm_b for x in vb]
            return sum(an[i] * M[i * n + j] * bn[j] for i in range(n) for j in range(n))

        scored = []
        for row in rows:
            if compat_matrix is not None:
                sim = bilinear(query_vector, compat_matrix, parse_vec(row.pvec))
            else:
                sim = row.cosine_sim
            scored.append((row.user_id, sim * geo_weight(row.latitude, row.longitude)))
        scored.sort(key=lambda x: -x[1])
        return [uid for uid, _ in scored[:top_k]]
