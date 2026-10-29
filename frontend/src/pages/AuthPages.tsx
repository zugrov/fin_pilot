import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";

const verifyAttempts = new Set<string>();
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { forgotPassword, login, register, resetPassword, verifyEmail } from "../api";
import { Button, Card, Field } from "../components/ui";

const credentials = z.object({
  email: z.string().email("Укажите почту"),
  password: z.string().min(12, "Минимум 12 символов"),
  name: z.string().min(1, "Укажите имя").optional(),
});

type FormValues = z.infer<typeof credentials>;

export function RegisterPage() {
  const navigate = useNavigate();
  const [notice, setNotice] = useState("");
  const form = useForm<FormValues>({ resolver: zodResolver(credentials) });
  return (
    <Card>
      <h1 className="mb-4 text-xl font-semibold">Регистрация</h1>
      <form
        onSubmit={form.handleSubmit(async (values) => {
          const result = await register(values.email, values.password, values.name ?? "Пользователь");
          setNotice(result.message);
          navigate("/login");
        })}
      >
        <Field label="Имя" {...form.register("name")} error={form.formState.errors.name?.message} />
        <Field label="Почта" type="email" {...form.register("email")} error={form.formState.errors.email?.message} />
        <Field label="Пароль" type="password" {...form.register("password")} error={form.formState.errors.password?.message} />
        <Button type="submit">Создать аккаунт</Button>
      </form>
      {notice ? <p className="mt-3 text-sm">{notice}</p> : null}
      <Link className="mt-4 block text-sm" to="/login">Уже есть аккаунт</Link>
    </Card>
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const form = useForm<FormValues>({ resolver: zodResolver(credentials.omit({ name: true })) });
  return (
    <Card>
      <h1 className="mb-4 text-xl font-semibold">Вход</h1>
      <form
        onSubmit={form.handleSubmit(async (values) => {
          try {
            await login(values.email, values.password);
            navigate("/billing");
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : "Не удалось войти");
          }
        })}
      >
        <Field label="Почта" type="email" {...form.register("email")} error={form.formState.errors.email?.message} />
        <Field label="Пароль" type="password" {...form.register("password")} error={form.formState.errors.password?.message} />
        {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
        <Button type="submit">Войти</Button>
      </form>
      <Link className="mt-4 block text-sm" to="/forgot-password">Забыли пароль</Link>
    </Card>
  );
}

export function VerifyPage() {
  const [params] = useSearchParams();
  const [message, setMessage] = useState("Подтверждаем почту…");
  const token = params.get("token") ?? "";
  useEffect(() => {
    if (!token) {
      setMessage("Ссылка неполная");
      return;
    }
    if (verifyAttempts.has(token)) {
      return;
    }
    verifyAttempts.add(token);
    verifyEmail(token)
      .then(() => setMessage("Почта подтверждена. Можно войти."))
      .catch((exc: unknown) => {
        verifyAttempts.delete(token);
        setMessage(exc instanceof Error ? exc.message : "Ссылка недействительна");
      });
  }, [token]);
  return (
    <Card>
      <h1 className="mb-4 text-xl font-semibold">Подтверждение почты</h1>
      <p>{message}</p>
      <Link className="mt-4 block text-sm" to="/login">Ко входу</Link>
    </Card>
  );
}

export function ForgotPage() {
  const [message, setMessage] = useState("");
  const form = useForm<{ email: string }>({
    resolver: zodResolver(z.object({ email: z.string().email() })),
  });
  return (
    <Card>
      <h1 className="mb-4 text-xl font-semibold">Сброс пароля</h1>
      <form
        onSubmit={form.handleSubmit(async (values) => {
          const result = await forgotPassword(values.email);
          setMessage(result.message);
        })}
      >
        <Field label="Почта" type="email" {...form.register("email")} />
        <Button type="submit">Отправить ссылку</Button>
      </form>
      {message ? <p className="mt-3 text-sm">{message}</p> : null}
    </Card>
  );
}

export function ResetPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const form = useForm<{ password: string }>({
    resolver: zodResolver(z.object({ password: z.string().min(12) })),
  });
  return (
    <Card>
      <h1 className="mb-4 text-xl font-semibold">Новый пароль</h1>
      <form
        onSubmit={form.handleSubmit(async (values) => {
          try {
            await resetPassword(params.get("token") ?? "", values.password);
            navigate("/login");
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : "Ссылка недействительна");
          }
        })}
      >
        <Field label="Новый пароль" type="password" {...form.register("password")} />
        {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
        <Button type="submit">Сохранить</Button>
      </form>
    </Card>
  );
}
