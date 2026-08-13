from src.db_service import (
    send_message_db,
    get_conversation_db,
    get_messages_for_user_db,
)


def send_message(vacancy_id, sender_id, receiver_id, message):
    if not message or not message.strip():
        return None, "Pesan tidak boleh kosong."
    result = send_message_db(vacancy_id, sender_id, receiver_id, message.strip())
    if result:
        return result, None
    return None, "Gagal mengirim pesan."


def get_conversation(vacancy_id, user_a_id, user_b_id):
    return get_conversation_db(vacancy_id, user_a_id, user_b_id)


def get_user_messages(user_id):
    return get_messages_for_user_db(user_id)
