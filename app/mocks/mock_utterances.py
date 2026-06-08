MOCK_UTTERANCES = [
    {"utterance_id": "utt_001", "speaker_role": "THERAPIST", "start_time": 0.5,  "end_time": 3.2,  "text": "오늘은 이 그림을 보고 이야기해볼까요?"},
    {"utterance_id": "utt_002", "speaker_role": "CHILD",     "start_time": 4.1,  "end_time": 5.8,  "text": "강아지가 있어요"},
    {"utterance_id": "utt_003", "speaker_role": "THERAPIST", "start_time": 6.0,  "end_time": 7.5,  "text": "강아지가 뭘 하고 있어요?"},
    {"utterance_id": "utt_004", "speaker_role": "CHILD",     "start_time": 9.2,  "end_time": 11.0, "text": "뛰어가요"},
    {"utterance_id": "utt_005", "speaker_role": "THERAPIST", "start_time": 11.5, "end_time": 13.0, "text": "맞아요, 강아지가 어디로 뛰어가요?"},
    {"utterance_id": "utt_006", "speaker_role": "CHILD",     "start_time": 15.0, "end_time": 17.2, "text": "공원에 가요"},
    {"utterance_id": "utt_007", "speaker_role": "THERAPIST", "start_time": 17.8, "end_time": 20.0, "text": "공원에서 뭘 했을까요?"},
    {"utterance_id": "utt_008", "speaker_role": "CHILD",     "start_time": 22.5, "end_time": 25.0, "text": "친구 만나요"},
    {"utterance_id": "utt_009", "speaker_role": "THERAPIST", "start_time": 25.5, "end_time": 27.0, "text": "친구랑 뭘 했어요?"},
    {"utterance_id": "utt_010", "speaker_role": "CHILD",     "start_time": 28.0, "end_time": 30.5, "text": "같이 놀았어요"},
]

MOCK_CHILD_UTTERANCES = [u for u in MOCK_UTTERANCES if u["speaker_role"] == "CHILD"]
