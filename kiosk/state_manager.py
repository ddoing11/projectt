class StateManager:
    """클라이언트 상태 관리"""
    
    def __init__(self):
        self.connected_clients = set()
        self.client_states = {}
        self.client_sessions = {}

    def create_initial_state(self):
        """초기 상태 생성"""
        return {
            "step": "init",
            "menu": None,
            "options": {},
            "price": 0,
            "category": None,
            "cart": [],
            "finalized": False,
            "first_order_done": False,
            "gpt_messages": []
        }

    def add_client(self, websocket):
        """클라이언트 추가"""
        self.connected_clients.add(websocket)
        self.client_states[websocket] = self.create_initial_state()
        return self.client_states[websocket]

    def remove_client(self, websocket):
        """클라이언트 제거"""
        if websocket in self.connected_clients:
            self.connected_clients.remove(websocket)
        if websocket in self.client_states:
            self.client_states.pop(websocket, None)

    def get_state(self, websocket):
        """상태 조회"""
        return self.client_states.get(websocket)

    def update_state(self, websocket, updates):
        """상태 업데이트"""
        if websocket in self.client_states:
            self.client_states[websocket].update(updates)

    def restore_session(self, client_id, websocket):
        """세션 복원"""
        if client_id in self.client_sessions:
            state = self.client_sessions[client_id]
        else:
            state = self.create_initial_state()
            self.client_sessions[client_id] = state
        
        self.client_states[websocket] = state
        return state

    def reset_order_state(self, websocket):
        """주문 상태 초기화"""
        state = self.get_state(websocket)
        if state:
            state.update({
                "step": "await_start",
                "menu": None,
                "options": {},
                "price": 0,
                "category": None,
                "cart": [],
                "finalized": False,
                "first_order_done": False
            })