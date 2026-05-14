const API_URL = '/api';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const getHeaders = () => {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  };
};

const parseResponse = async (res: Response) => {
  let data: any = null;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    data = await res.json();
  }

  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
  }

  if (!res.ok) {
    throw new ApiError(res.status, data?.detail || '请求失败');
  }

  return data;
};

export const api = {
  async post(path: string, body?: any) {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: getHeaders(),
      body: body ? JSON.stringify(body) : undefined
    });
    return parseResponse(res);
  },
  async get(path: string) {
    const res = await fetch(`${API_URL}${path}`, {
      headers: getHeaders()
    });
    return parseResponse(res);
  },
  async put(path: string, body: any) {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify(body)
    });
    return parseResponse(res);
  },
  async patch(path: string, body: any) {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'PATCH',
      headers: getHeaders(),
      body: JSON.stringify(body)
    });
    return parseResponse(res);
  },
  async delete(path: string) {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'DELETE',
      headers: getHeaders()
    });
    return parseResponse(res);
  },
  async login(username: string, password: string) {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);
    const res = await fetch(`${API_URL}/login`, {
      method: 'POST',
      body: formData
    });
    return parseResponse(res);
  }
};
