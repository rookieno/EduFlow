_SAMPLE_COVER_ALT = {
    "digital-project-lab": "종이 화면 스케치와 노트북의 프로토타입을 비교하는 작업대",
    "ux-research-workshop": "디자인 스튜디오에서 사용자 인터뷰를 진행하는 두 사람",
    "python-data-studio": "파이썬 노트북과 데이터 차트가 표시된 노트북 화면",
    "product-storytelling": "제품 이야기를 장면별로 구성한 종이 스토리보드",
    "service-prototype-clinic": "휴대전화 서비스 화면과 사용성 확인표를 함께 살펴보는 손",
    "design-sprint-archive": "벽에 붙인 메모와 스케치를 정리하는 디자인 스프린트 팀",
}


def sample_course_cover_alt(slug: str) -> str:
    return _SAMPLE_COVER_ALT.get(slug, "")
