"use client";

// Страница профиля: данные учётной записи и выход.
//
// Назначение: показать, под кем выполнен вход, какие права у пользователя и
// когда создана запись. Даёт точку для действий с сессией.
//
// Место в архитектуре: клиентская страница внутри AppShell; данные берёт из
// `GET /auth/me`.
//
// Что здесь СОЗНАТЕЛЬНО не реализовано и почему:
// - смена пароля: в API нет эндпоинта смены пароля, а придумывать его нельзя;
// - API-токены: их выпуск в проекте не предусмотрен, вход выполняется JWT;
// - экспорт данных: полный экспорт — задача уровня бэкапа, а диалог
//   экспортируется отдельно (`GET /conversations/{id}/export`).
// Вместо неработающих форм эти пункты описаны словами с указанием, где взять
// соответствующую функциональность.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, LogOut, ShieldCheck, UserRound } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, getToken, setToken, User } from "@/lib/api";

/**
 * Страница профиля пользователя.
 *
 * @returns Разметку с данными учётной записи и действием выхода.
 */
export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    api
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          setToken(null);
          router.push("/login");
          return;
        }
        setError(
          err instanceof Error ? err.message : "Не удалось загрузить профиль.",
        );
      })
      .finally(() => setLoading(false));
  }, [router]);

  /** Завершает сессию и возвращает на страницу входа. */
  function logout() {
    setToken(null);
    router.push("/login");
  }

  return (
    <AppShell
      title="Профиль"
      description="Учётная запись и текущая сессия."
      actions={
        <Button variant="outline" size="sm" onClick={logout}>
          <LogOut />
          Выйти
        </Button>
      }
    >
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-48" />
          </CardContent>
        </Card>
      ) : user ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserRound className="size-4" aria-hidden="true" />
                Учётная запись
              </CardTitle>
              <CardDescription>
                Данные берутся из текущей сессии.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-muted-foreground w-32 text-sm">
                  Имя пользователя
                </span>
                <span className="font-medium">{user.username}</span>
              </div>
              <Separator />
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-muted-foreground w-32 text-sm">
                  Права
                </span>
                {user.is_admin ? (
                  <Badge variant="success">
                    <ShieldCheck aria-hidden="true" />
                    Администратор
                  </Badge>
                ) : (
                  <Badge variant="secondary">Пользователь</Badge>
                )}
              </div>
              <Separator />
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-muted-foreground w-32 text-sm">
                  Идентификатор
                </span>
                <code className="text-pah-sm">{user.id}</code>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="size-4" aria-hidden="true" />
                Безопасность
              </CardTitle>
              <CardDescription>
                Как устроены вход и хранение секретов.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-muted-foreground space-y-3 text-sm">
              <p>
                Пароль хранится в виде хеша Argon2id, восстановление пароля
                недоступно: платформа работает локально и не отправляет письма.
              </p>
              <p>
                Ключи провайдеров шифруются мастер-ключом приложения и никогда
                не возвращаются в интерфейс — видна только маска.
              </p>
              <p>
                Сессия — это JWT, выданный после входа. Выход удаляет его из
                браузера. Чтобы завершить все сессии сразу, смените{" "}
                <code>APP_MASTER_KEY</code> и перезапустите стек.
              </p>
            </CardContent>
          </Card>
        </>
      ) : null}
    </AppShell>
  );
}
