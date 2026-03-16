import React, { useRef, useMemo, useState, useEffect, useCallback } from "react";
import { Box, Text, VStack, Select, Input, Button, HStack, IconButton } from "@chakra-ui/react";
import { FaPlus, FaTrash, FaChevronDown, FaChevronUp } from "react-icons/fa";

import { useVariableInsertion } from "@/hooks/graphs/useVariableInsertion";
import VariableSelector from "../../Common/VariableSelector";
import { VariableReference } from "../../FlowVis/variableSystem";

// 类型定义
interface HttpPropertiesProps {
  node: {
    id: string;
    data?: {
      url?: string;
      method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "HEAD";
      headers?: Record<string, string>;
      queryParams?: Record<string, string>;
      body?: string | Record<string, any>;
      timeout?: number;
    };
  };
  onNodeDataChange: (nodeId: string, key: string, value: any) => void;
  availableVariables: VariableReference[];
}

interface KeyValueItem {
  id: string;
  key: string;
  value: string;
}

// 生成唯一ID
const generateId = () => Math.random().toString(36).substr(2, 9);

// 统一输入框样式配置
const INPUT_STYLE = {
  size: "sm" as const,
  height: "2.5rem",
  padding: "0.5rem 0.75rem",
  fontSize: "0.875rem",
  borderRadius: "0.375rem",
  borderWidth: "1px"
};

// 键值对组件
const KeyValueItem: React.FC<{
  item: KeyValueItem;
  onItemChange: (id: string, field: "key" | "value", value: string) => void;
  onRemove: (id: string) => void;
  withVariable?: boolean;
  availableVariables?: VariableReference[];
}> = React.memo(({ 
  item, 
  onItemChange, 
  onRemove, 
  withVariable = false, 
  availableVariables = [] 
}) => {
  const [value, setValue] = useState(item.value);
  const valueRef = useRef<HTMLInputElement>(null);
  const [slashTriggered, setSlashTriggered] = useState(false);

  // 同步外部value变化
  useEffect(() => {
    setValue(item.value);
  }, [item.value]);

  // 变量插入逻辑
  const {
    showVariables,
    setShowVariables,
    handleKeyDown: baseHandleKeyDown,
  } = useVariableInsertion<HTMLInputElement>({
    onValueChange: (newValue) => {
      setValue(newValue);
      onItemChange(item.id, "value", newValue);
      // 输入其他内容时重置斜杠触发状态
      if (slashTriggered) {
        setShowVariables(false);
        setSlashTriggered(false);
      }
    },
    availableVariables,
    initialValue: value,
    ref: valueRef,
    disabled: !withVariable,
  });

  // 处理键盘事件：输入斜杠时显示变量选择面板，但保留斜杠
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    baseHandleKeyDown(e);
    
    // 输入斜杠时显示变量选择面板
    if (e.key === "/" && withVariable) {
      // 先让斜杠显示在输入框中
      const cursorPos = valueRef.current?.selectionStart || value.length;
      const newVal = value.substring(0, cursorPos) + "/" + value.substring(cursorPos);
      setValue(newVal);
      onItemChange(item.id, "value", newVal);
      
      // 显示变量选择面板
      setShowVariables(true);
      setSlashTriggered(true);
      
      // 阻止默认行为，避免重复输入
      e.preventDefault();
    } else if (slashTriggered && e.key !== "Tab") {
      // 输入其他内容时关闭变量面板
      setShowVariables(false);
      setSlashTriggered(false);
    }
  }, [baseHandleKeyDown, withVariable, value, item.id, onItemChange, slashTriggered]);

  const handleInsertVariable = useCallback((variable: VariableReference | string) => {
    try {
      const variableName = typeof variable === "string" 
        ? variable 
        : variable?.name;

      if (!variableName) throw new Error("无效变量");

      // 替换最后一个斜杠为变量
      const lastSlashIndex = value.lastIndexOf("/");
      if (lastSlashIndex !== -1) {
        const newValue = value.substring(0, lastSlashIndex) + `{${variableName}}` + value.substring(lastSlashIndex + 1);
        setValue(newValue);
        onItemChange(item.id, "value", newValue);
      } else {
        // 如果没有斜杠，直接在末尾添加变量
        const newValue = `${value}{${variableName}}`;
        setValue(newValue);
        onItemChange(item.id, "value", newValue);
      }
      
      valueRef.current?.focus();
      setShowVariables(false);
      setSlashTriggered(false);
    } catch (error) {
      console.error("变量插入失败:", error);
    }
  }, [value, item.id, onItemChange, setShowVariables]);

  return (
    <HStack key={item.id} spacing={3} align="center" width="100%">
       <Input
          {...INPUT_STYLE}
          placeholder="Key"
          value={item.key}
          onChange={(e) =>
            onItemChange(item.id, "key", e.target.value)
          }
        />
      
       <VariableSelector
          {...INPUT_STYLE}
          placeholder="Value"
          value={value}
          onChange={(newValue) => {
            setValue(newValue);
            onItemChange(item.id, "value", newValue);
            setShowVariables(false);
            setSlashTriggered(false);
          }}
          showVariables={showVariables}
          setShowVariables={setShowVariables}
          ref={valueRef}
          handleKeyDown={handleKeyDown}
          insertVariable={handleInsertVariable}
          availableVariables={availableVariables}
          isInput
          disabled={!withVariable}
        />
      
      <IconButton
        size="sm"
        icon={<FaTrash size={14} />}
        onClick={(e) => {
          e.stopPropagation();
          onRemove(item.id);
        }}
        colorScheme="red"
        variant="ghost"
        aria-label="删除"
      />
    </HStack>
  );
});

// 通用折叠面板组件
const CollapsibleSection: React.FC<{
  title: string;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  actionButton?: React.ReactNode;
}> = ({ title, isExpanded, onToggle, children, actionButton }) => (
  <Box borderWidth="1px" borderRadius="lg" overflow="hidden" mb={3}>
    <HStack 
      justify="space-between" 
      align="center" 
      p={2}
      bg="gray.50"
      cursor="pointer"
    >
      <Text fontWeight="500" fontSize="sm">{title}</Text>
      <HStack spacing={2}>
        {actionButton}
        <IconButton
          size="sm"
          icon={isExpanded ? <FaChevronUp /> : <FaChevronDown />}
          onClick={onToggle}
          variant="ghost"
          aria-label={isExpanded ? "折叠" : "展开"}
        />
      </HStack>
    </HStack>
    
    {isExpanded && (
      <VStack p={3} spacing={3} align="stretch">
        {children}
      </VStack>
    )}
  </Box>
);

// 请求体组件
const RequestBodySection: React.FC<{
  body: string;
  isExpanded: boolean;
  onToggle: () => void;
  onBodyChange: (value: string) => void;
  availableVariables: VariableReference[];
}> = ({ body, isExpanded, onToggle, onBodyChange, availableVariables }) => {
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [currentBody, setCurrentBody] = useState(body);
  const [slashTriggered, setSlashTriggered] = useState(false);

  // 同步外部body变化
  useEffect(() => {
    setCurrentBody(body);
  }, [body]);

  const {
    showVariables,
    setShowVariables,
    handleKeyDown: baseHandleKeyDown,
  } = useVariableInsertion<HTMLTextAreaElement>({
    onValueChange: (newValue) => {
      setCurrentBody(newValue);
      onBodyChange(newValue);
      if (slashTriggered) {
        setShowVariables(false);
        setSlashTriggered(false);
      }
    },
    availableVariables,
    initialValue: currentBody,
    ref: bodyRef,
  });

  // 处理键盘事件：输入斜杠时显示变量选择面板
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    baseHandleKeyDown(e);
    
    if (e.key === "/") {
      // 先将斜杠添加到输入框
      const cursorPos = bodyRef.current?.selectionStart || currentBody.length;
      const newVal = currentBody.substring(0, cursorPos) + "/" + currentBody.substring(cursorPos);
      setCurrentBody(newVal);
      onBodyChange(newVal);
      
      // 显示变量选择面板
      setShowVariables(true);
      setSlashTriggered(true);
      
      // 阻止默认行为，避免重复输入
      e.preventDefault();
    } else if (slashTriggered && e.key !== "Tab") {
      // 输入其他内容时关闭变量面板
      setShowVariables(false);
      setSlashTriggered(false);
    }
  }, [baseHandleKeyDown, currentBody, onBodyChange, slashTriggered]);

  const handleInsertVariable = useCallback((variable: VariableReference | string) => {
    try {
      const variableName = typeof variable === "string" 
        ? variable 
        : variable?.name;

      if (!variableName) throw new Error("无效变量");

      // 替换最后一个斜杠为变量
      const lastSlashIndex = currentBody.lastIndexOf("/");
      const newValue = lastSlashIndex !== -1
        ? currentBody.substring(0, lastSlashIndex) + `{${variableName}}` + currentBody.substring(lastSlashIndex + 1)
        : `${currentBody}{${variableName}}`;
      
      setCurrentBody(newValue);
      onBodyChange(newValue);
      bodyRef.current?.focus();
      setShowVariables(false);
      setSlashTriggered(false);
    } catch (error) {
      console.error("变量插入失败:", error);
    }
  }, [currentBody, onBodyChange, setShowVariables]);

  return (
    <CollapsibleSection
      title="Request Body (JSON)"
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <VariableSelector
        value={currentBody}
        onChange={(newValue) => {
          setCurrentBody(newValue);
          onBodyChange(newValue);
          setShowVariables(false);
          setSlashTriggered(false);
        }}
        placeholder='{"key": "value"}'
        showVariables={showVariables}
        setShowVariables={setShowVariables}
        ref={bodyRef}
        handleKeyDown={handleKeyDown}
        insertVariable={handleInsertVariable}
        availableVariables={availableVariables}
        minHeight="150px"
        monospace
      />
    </CollapsibleSection>
  );
};

const HttpProperties: React.FC<HttpPropertiesProps> = ({
  node,
  onNodeDataChange,
  availableVariables,
}) => {
  // 状态初始化
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState<"GET" | "POST" | "PUT" | "DELETE" | "PATCH"| "HEAD">("GET");
  const [headers, setHeaders] = useState<KeyValueItem[]>([]);
  const [params, setParams] = useState<KeyValueItem[]>([]);
  const [body, setBody] = useState("");
  const [timeout, setTimeoutValue] = useState(30);
  const [expandedSections, setExpandedSections] = useState({
    headers: true,
    body: true,
    params: true,
  });

  const urlRef = useRef<HTMLInputElement>(null);
  const [slashTriggered, setSlashTriggered] = useState(false);

  // 初始化数据
  useEffect(() => {
    if (!node.data) return;

    const { url, method, headers, queryParams, body, timeout } = node.data;
    
    setUrl(url || "");
    setMethod(["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"].includes(method as string) 
      ? (method as "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "HEAD") 
      : "GET"
    );
    const initialTimeout = node.data?.timeout ?? 30;
    setTimeoutValue(Math.min(Math.max(1, initialTimeout), 120));
    setBody(
      typeof body === "object" && body !== null 
        ? JSON.stringify(body, null, 2) 
        : (body as string) || ""
    );
    
    // 初始化headers
    setHeaders(
      headers && Object.keys(headers).length > 0
        ? Object.entries(headers).map(([k, v]) => ({ 
            id: generateId(), 
            key: k, 
            value: String(v)
          }))
        : [{ id: generateId(), key: "", value: "" }]
    );
    
    // 初始化queryParams
    setParams(
      queryParams && Object.keys(queryParams).length > 0
        ? Object.entries(queryParams).map(([k, v]) => ({ 
            id: generateId(), 
            key: k, 
            value: String(v)
          }))
        : [{ id: generateId(), key: "", value: "" }]
    );
  }, [node.data]);

  // URL变量插入逻辑
  const {
    showVariables: showUrlVariables,
    setShowVariables: setShowUrlVariables,
    handleKeyDown: baseHandleUrlKeyDown,
  } = useVariableInsertion<HTMLInputElement>({
    onValueChange: (value) => {
      setUrl(value);
      onNodeDataChange(node.id, "url", value);
      if (slashTriggered) {
        setShowUrlVariables(false);
        setSlashTriggered(false);
      }
    },
    availableVariables,
    initialValue: url,
    ref: urlRef,
  });

  // 处理URL键盘事件：输入斜杠时显示变量选择面板
  const handleUrlKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    baseHandleUrlKeyDown(e);
    
    if (e.key === "/") {
      // 先将斜杠添加到输入框
      const cursorPos = urlRef.current?.selectionStart || url.length;
      const newVal = url.substring(0, cursorPos) + "/" + url.substring(cursorPos);
      setUrl(newVal);
      onNodeDataChange(node.id, "url", newVal);
      
      // 显示变量选择面板
      setShowUrlVariables(true);
      setSlashTriggered(true);
      
      // 阻止默认行为，避免重复输入
      e.preventDefault();
    } else if (slashTriggered && e.key !== "Tab") {
      // 输入其他内容时关闭变量面板
      setShowUrlVariables(false);
      setSlashTriggered(false);
    }
  }, [baseHandleUrlKeyDown, url, node.id, onNodeDataChange, slashTriggered]);

  const handleUrlInsertVariable = useCallback((variable: VariableReference | string) => {
    try {
      const variableName = typeof variable === "string" 
        ? variable 
        : variable?.name;

      if (!variableName) throw new Error("无效变量");

      // 替换最后一个斜杠为变量
      const lastSlashIndex = url.lastIndexOf("/");
      const newValue = lastSlashIndex !== -1
        ? url.substring(0, lastSlashIndex) + `{${variableName}}` + url.substring(lastSlashIndex + 1)
        : `${url}{${variableName}}`;
      
      setUrl(newValue);
      onNodeDataChange(node.id, "url", newValue);
      urlRef.current?.focus();
      setShowUrlVariables(false);
      setSlashTriggered(false);
    } catch (error) {
      console.error("URL变量插入失败:", error);
    }
  }, [url, node.id, onNodeDataChange, setShowUrlVariables]);

  // 处理方法变更
  const handleMethodChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const newMethod = e.target.value as "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "HEAD";
    setMethod(newMethod);
    onNodeDataChange(node.id, "method", newMethod);
  }, [node.id, onNodeDataChange]);

  const handleTimeoutChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputValue = e.target.value.trim();
    if (inputValue === "") {
      setTimeoutValue("" as unknown as number);
    } else {
      const num = parseInt(inputValue, 10);
      if (!isNaN(num)) {
        setTimeoutValue(num);
      }
    }
  };

  // 失焦时修正为合法值
  const handleBlur = () => {
    let validValue;
    if (timeout === "" || isNaN(timeout)) {
      validValue = 30;
    } else {
      validValue = Math.min(Math.max(1, timeout), 120);
    }
    setTimeoutValue(validValue);
    onNodeDataChange(node.id, "timeout", validValue);
  };

  // 折叠面板控制
  const toggleSection = useCallback((section: keyof typeof expandedSections) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  }, []);

  // Headers处理
  const handleHeaderChange = useCallback((id: string, field: "key" | "value", value: string) => {
    const processedValue = field === "key" 
      ? value.trim().replace(/\s+/g, '_') 
      : value.trim();
    
    const newHeaders = headers.map(h => 
      h.id === id ? { ...h, [field]: processedValue } : h
    );
    
    setHeaders(newHeaders);
    
    const headersDict = newHeaders.reduce((obj, item) => {
      if (item.key) {
        return { ...obj, [item.key]: item.value };
      }
      return obj;
    }, {} as Record<string, string>);
    
    onNodeDataChange(node.id, "headers", headersDict);
  }, [headers, node.id, onNodeDataChange]);

  // 添加新的header行
  const addHeader = useCallback(() => {
    setHeaders([...headers, { id: generateId(), key: "", value: "" }]);
  }, [headers]);

  // 删除header行
  const removeHeader = useCallback((id: string) => {
    const newHeaders = headers.filter(h => h.id !== id);
    setHeaders(newHeaders.length > 0 ? newHeaders : [{ id: generateId(), key: "", value: "" }]);
    
    const headersDict = newHeaders.reduce((obj, item) => {
      if (item.key) {
        return { ...obj, [item.key]: item.value };
      }
      return obj;
    }, {} as Record<string, string>);
    
    onNodeDataChange(node.id, "headers", headersDict);
  }, [headers, node.id, onNodeDataChange]);

  // QueryParams处理
  const handleParamChange = useCallback((id: string, field: "key" | "value", value: string) => {
    const processedValue = field === "key" 
      ? value.trim().replace(/\s+/g, '_') 
      : value.trim();
      
    const newParams = params.map(p => p.id === id ? { ...p, [field]: processedValue } : p);
    setParams(newParams);
    
    onNodeDataChange(
      node.id, 
      "queryParams", 
      newParams.reduce((obj, item) => (item.key ? { ...obj, [item.key]: item.value } : obj), {})
    );
  }, [params, node.id, onNodeDataChange]);

  const addParam = useCallback(() => {
    setParams([...params, { id: generateId(), key: "", value: "" }]);
  }, [params]);

  const removeParam = useCallback((id: string) => {
    const newParams = params.filter(p => p.id !== id);
    setParams(newParams.length > 0 ? newParams : [{ id: generateId(), key: "", value: "" }]);
    
    onNodeDataChange(
      node.id, 
      "queryParams", 
      newParams.reduce((obj, item) => (item.key ? { ...obj, [item.key]: item.value } : obj), {})
    );
  }, [params, node.id, onNodeDataChange]);

  // 请求体处理
  const handleBodyChange = useCallback((value: string) => {
    setBody(value);
    try {
      const parsed = value ? JSON.parse(value) : {};
      onNodeDataChange(node.id, "body", parsed);
    } catch {
      onNodeDataChange(node.id, "body", value);
    }
  }, [node.id, onNodeDataChange]);

  // 缓存headers渲染
  const memoizedHeaders = useMemo(() => (
    headers.map(header => (
      <KeyValueItem
        key={header.id}
        item={header}
        onItemChange={handleHeaderChange}
        onRemove={removeHeader}
        withVariable
        availableVariables={availableVariables}
      />
    ))
  ), [headers, handleHeaderChange, removeHeader, availableVariables]);

  // 缓存params渲染
  const memoizedParams = useMemo(() => (
    params.map(param => (
      <KeyValueItem
        key={param.id}
        item={param}
        onItemChange={handleParamChange}
        onRemove={removeParam}
        withVariable
        availableVariables={availableVariables}
      />
    ))
  ), [params, handleParamChange, removeParam, availableVariables]);

  return (
    <VStack align="stretch" spacing={4} p={3}>
      {/* URL输入区域 */}
      <VariableSelector
        label="URL"
        value={url}
        onChange={(value) => {
          setUrl(value);
          onNodeDataChange(node.id, "url", value);
          setShowUrlVariables(false);
          setSlashTriggered(false);
        }}
        placeholder="https://api.example.com/endpoint"
        showVariables={showUrlVariables}
        setShowVariables={setShowUrlVariables}
        ref={urlRef}
        handleKeyDown={handleUrlKeyDown}
        insertVariable={handleUrlInsertVariable}
        availableVariables={availableVariables}
        isInput
        size="md"
      />

      {/* 方法和超时设置 */}
      <HStack spacing={4}>
        <Box flex={1}>
          <Text fontWeight="500" fontSize="sm" color="gray.700" mb={1}>Method</Text>
          <Select
            value={method}
            onChange={handleMethodChange}
            size={INPUT_STYLE.size}
            height={INPUT_STYLE.height}
            fontSize={INPUT_STYLE.fontSize}
          >
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="DELETE">DELETE</option>
            <option value="PATCH">PATCH</option>
            <option value="HEAD">HEAD</option>
          </Select>
        </Box>

        <Box flex={1}>
          <Text fontWeight="500" fontSize="sm" color="gray.700" mb={1}>Timeout (s)</Text>
          <Input
            type="number"
            value={timeout}
            onBlur={handleBlur}
            onChange={handleTimeoutChange}
            {...INPUT_STYLE}
            min={1}
            max={120}
            placeholder="输入超时时间（1-120）"
          />
        </Box>
      </HStack>

      {/* Headers区域 */}
      <CollapsibleSection
        title="Headers"
        isExpanded={expandedSections.headers}
        onToggle={() => toggleSection('headers')}
        actionButton={
          <Button
            size="sm"
            leftIcon={<FaPlus />}
            onClick={(e) => {
              e.stopPropagation();
              addHeader();
            }}
            variant="outline"
          >
            添加Header
          </Button>
        }
      >
        {memoizedHeaders}
      </CollapsibleSection>

      {(method === "GET" || method === "DELETE" || method === "HEAD") && (
        <CollapsibleSection
          title="Query Parameters"
          isExpanded={expandedSections.params}
          onToggle={() => toggleSection('params')}
          actionButton={
            <Button
              size="sm"
              leftIcon={<FaPlus />}
              onClick={(e) => {
                e.stopPropagation();
                addParam();
              }}
              variant="outline"
            >
              添加参数
            </Button>
          }
        >
          {memoizedParams}
        </CollapsibleSection>
      )}
      
      {(method === "POST" || method === "PUT" || method === "PATCH") && (
        <RequestBodySection
          body={body}
          isExpanded={expandedSections.body}
          onToggle={() => toggleSection('body')}
          onBodyChange={handleBodyChange}
          availableVariables={availableVariables}
        />
      )}
    </VStack>
  );
};

export default React.memo(HttpProperties);